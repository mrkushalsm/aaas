#!/usr/bin/env python3
"""Validate staged mixed-composition evidence from one stopped AaaS session."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


_CREATE = re.compile(r"createVirtualDisplay id=(\d+) size=(\d+)x(\d+)")
_OUTPUT = re.compile(
    r"virtual output frame display=(\d+) slot=\d+ generation=(\d+) "
    r"buffer_id=(\d+) width=(\d+) height=(\d+) stride=(\d+) "
    r"dma_dev=(\d+) dma_ino=(\d+)"
)
_MIXED = re.compile(
    r"mixed-frame verify display=(\d+) layer=(\d+) .*? "
    r"src=(\d+):(\d+) dst=(\d+):(\d+) .*?pixels=exact"
)
_COMPOSITION = re.compile(
    r"virtual composition display=(\d+) .*selected_device_layer=(-?\d+)"
)
_SUBMIT = re.compile(
    r"Submitting frame id=(\d+) \(slot=\d+, .*backing_dev=(\d+), backing_ino=(\d+)"
)
_FATAL = re.compile(r"FATAL EXCEPTION|Fatal signal|ANR in |SIGSEGV")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _events(path: Path) -> list[dict[str, Any]]:
    result = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("{"):
            value = json.loads(line)
            if value.get("role") == "presenter" and value.get("event"):
                result.append(value)
    return result


def analyze(session_dir: Path, composer_log: Path, mode: str) -> dict[str, Any]:
    session_dir = session_dir.resolve()
    composer_log = composer_log.resolve()
    status = (session_dir / "status").read_text().strip()
    if status != "STOPPED":
        raise ValueError(f"session status is {status}, expected STOPPED")

    states = [json.loads(line) for line in (session_dir / "state.jsonl").read_text().splitlines()]
    if not states or states[-1].get("state") != "STOPPED":
        raise ValueError("state journal does not terminate at STOPPED")

    lines = composer_log.read_text(errors="replace").splitlines()
    created: dict[str, tuple[int, int]] = {}
    output_backings: dict[str, set[tuple[int, int]]] = defaultdict(set)
    exact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_mode: dict[str, str] = {}
    pending_submission: dict[tuple[int, int], deque[int]] = defaultdict(deque)
    frame_mode: dict[tuple[int, int, int], str] = {}
    for line in lines:
        match = _COMPOSITION.search(line)
        if match:
            selected_mode[match.group(1)] = "mixed" if int(match.group(2)) != -1 else "alias"
        match = _SUBMIT.search(line)
        if match:
            frame_id, dev, ino = map(int, match.groups())
            pending_submission[(dev, ino)].append(frame_id)
        match = _CREATE.search(line)
        if match:
            created[match.group(1)] = (int(match.group(2)), int(match.group(3)))
        match = _OUTPUT.search(line)
        if match:
            display = match.group(1)
            backing = (int(match.group(7)), int(match.group(8)))
            output_backings[display].add(backing)
            queued = pending_submission.get(backing)
            if queued and display in selected_mode:
                frame_id = queued.popleft()
                frame_mode[(frame_id, backing[0], backing[1])] = selected_mode[display]
        match = _MIXED.search(line)
        if match:
            display, layer, src_dev, src_ino, dst_dev, dst_ino = match.groups()
            source = (int(src_dev), int(src_ino))
            destination = (int(dst_dev), int(dst_ino))
            if source == destination:
                raise ValueError(f"mixed display {display} aliased CLIENT and output backing")
            exact[display].append({"layer": int(layer), "source": source, "destination": destination})

    broker = session_dir / "ipc" / "display_broker.log"
    broker_text = broker.read_text(errors="replace")
    if not re.search(r"created index=0 displayId=\d+", broker_text):
        raise ValueError("display broker did not create app display 1")
    if not re.search(r"created index=1 displayId=\d+", broker_text):
        raise ValueError("display broker did not create app display 2")

    presenters = []
    slot_maps = []
    for slot, filename in ((1, "virtual-presenter.log"), (2, "virtual-presenter2.log")):
        path = session_dir / filename
        events = _events(path)
        summaries = [event for event in events if event["event"] == "summary"]
        if not summaries:
            raise ValueError(f"slot {slot} has no presenter summary")
        # A slot can be closed and reopened during a session. Each presenter
        # process writes its own terminal summary to the shared slot log.
        summary = {}
        for key in (
            "imports", "submissions", "releases", "rejected", "presented",
            "discarded", "input_sent", "input_dropped", "teardown_invalidated",
            "user_us", "system_us",
        ):
            summary[key] = sum(int(item.get(key, 0)) for item in summaries)
        summary["outstanding"] = max(int(item.get("outstanding", 0)) for item in summaries)
        summary["maxrss_kib"] = max(int(item.get("maxrss_kib", 0)) for item in summaries)
        summary["presenter_lifecycles"] = len(summaries)
        for key in ("imports", "submissions", "releases"):
            if summary.get(key) != summary.get("imports"):
                raise ValueError(f"slot {slot} has unbalanced {key}: {summary}")
        if summary.get("outstanding") != 0 or summary.get("teardown_invalidated") != 0:
            raise ValueError(f"slot {slot} did not release all Wayland buffers: {summary}")

        by_frame: dict[tuple[int, int], dict[str, dict[str, Any]]] = defaultdict(dict)
        for event in events:
            if event["event"] in {
                "transport_buffer_received", "staging_copy", "source_copy_complete",
                "wayland_buffer_imported", "frame_committed", "buffer_release",
            }:
                key = (int(event.get("generation", -1)), int(event.get("id", -1)))
                by_frame[key][event["event"]] = event

        staged = 0
        staging_us = []
        staging_us_by_mode: dict[str, list[int]] = {"alias": [], "mixed": [], "unclassified": []}
        transport_backings = set()
        frame_identities = []
        for key, frame in by_frame.items():
            received = frame.get("transport_buffer_received")
            imported = frame.get("wayland_buffer_imported")
            if received and received.get("fstat_ok"):
                transport_backings.add((int(received["dma_dev"]), int(received["dma_ino"])))
            if not received or not imported:
                continue
            if imported.get("staged_copy") is not True:
                raise ValueError(f"slot {slot} frame {key} did not use staging")
            source_backing = (int(received["dma_dev"]), int(received["dma_ino"]))
            staged_backing = (int(imported["dma_dev"]), int(imported["dma_ino"]))
            if source_backing == staged_backing:
                raise ValueError(f"slot {slot} frame {key} reused Composer output as staging")
            copy = frame.get("staging_copy")
            complete = frame.get("source_copy_complete")
            commit = frame.get("frame_committed")
            release = frame.get("buffer_release")
            if not copy or not complete or not commit or not release:
                raise ValueError(f"slot {slot} frame {key} lacks copy/commit/release events")
            if not (copy["t_ns"] <= complete["t_ns"] <= imported["t_ns"]
                    <= commit["t_ns"] <= release["t_ns"]):
                raise ValueError(f"slot {slot} frame {key} violates copy/commit/release order")
            if not commit.get("explicit_sync"):
                raise ValueError(f"slot {slot} frame {key} was committed without explicit sync")
            staged += 1
            frame_identities.append({
                "generation": key[0],
                "frame_id": key[1],
                "composer_output_backing": list(source_backing),
                "wayland_staging_backing": list(staged_backing),
                "staging_pipeline_complete_ns": int(copy["t_ns"]),
                "source_copy_complete_ns": int(complete["t_ns"]),
                "wayland_import_ns": int(imported["t_ns"]),
                "frame_commit_ns": int(commit["t_ns"]),
                "wayland_release_ns": int(release["t_ns"]),
                "explicit_sync": bool(commit.get("explicit_sync")),
            })
            if "overhead_us" in copy:
                measured_us = int(copy["overhead_us"])
                staging_us.append(measured_us)
                composition_mode = frame_mode.get(
                    (key[1], source_backing[0], source_backing[1]), "unclassified"
                )
                staging_us_by_mode[composition_mode].append(measured_us)

        matched = []
        for display, backings in output_backings.items():
            if backings & transport_backings and exact.get(display):
                exact_backings = {entry["destination"] for entry in exact[display]}
                intersection = exact_backings & transport_backings
                if intersection:
                    matched.append({
                        "composer_display_id": int(display),
                        "initial_or_resize_geometry": created.get(display),
                        "exact_pixel_checks": len(exact[display]),
                        "exact_output_backing_matches_presenter_source": len(intersection),
                        "matched_backing_identities": [list(identity) for identity in sorted(intersection)],
                    })
        if not matched:
            raise ValueError(f"slot {slot} has no exact mixed output matching its transport")
        if staged != summary["imports"]:
            raise ValueError(f"slot {slot} staged {staged} of {summary['imports']} imports")
        slot_maps.append({"slot": slot, "matched_composer_outputs": matched})
        presenters.append({
            "slot": slot,
            "log": str(path),
            "sha256": _sha256(path),
            "summary": {key: summary.get(key) for key in (
                "imports", "submissions", "releases", "rejected", "presented",
                "discarded", "input_sent", "input_dropped", "outstanding",
                "teardown_invalidated", "maxrss_kib", "presenter_lifecycles",
            )},
            "staged_frames": staged,
            "staged_frame_identity_samples": [
                frame_identities[index]
                for index in sorted({0, len(frame_identities) // 2, len(frame_identities) - 1})
            ],
            "staging_pipeline_us": ({
                "p50": statistics.median(staging_us),
                "p95": sorted(staging_us)[int(0.95 * (len(staging_us) - 1))],
                "max": max(staging_us),
            } if staging_us else None),
            "staging_pipeline_measurement_scope": (
                "presenter t0-to-t1 includes GBM allocation, DMA-BUF synchronization, mapping, visible-row copy, and export; acquire-fence wait precedes t0"
            ),
            "staging_pipeline_by_composition": {
                mode: {
                    "frames": len(values),
                    "p50": statistics.median(values),
                    "p95": sorted(values)[int(0.95 * (len(values) - 1))],
                    "max": max(values),
                }
                for mode, values in staging_us_by_mode.items() if values
            },
        })

    logcat = (session_dir / "logcat.log").read_text(errors="replace")
    fatal_count = len(_FATAL.findall(logcat))
    if fatal_count:
        raise ValueError(f"session logcat has {fatal_count} fatal/ANR markers")

    return {
        "session_id": session_dir.name,
        "mode": mode,
        "status": status,
        "state_journal_sha256": _sha256(session_dir / "state.jsonl"),
        "composer_log": str(composer_log),
        "composer_log_sha256": _sha256(composer_log),
        "virtual_outputs": [
            {"composer_display_id": int(display), "size": list(size)}
            for display, size in sorted(created.items(), key=lambda item: int(item[0]))
        ],
        "presenter_output_correlations": slot_maps,
        "presenters": presenters,
        "fatal_or_anr_markers": fatal_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--composer-log", type=Path, required=True)
    parser.add_argument("--mode", choices=("default", "enhanced"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.session_dir, args.composer_log, args.mode)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
