#!/usr/bin/env python3
"""Summarize opt-in AaaS presenter staging and presentation timing events."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def percentile(values: list[int | float], fraction: float) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def distribution(values: list[int | float], unit: str) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"samples": 0, "unit": unit}
    p25 = percentile(ordered, 0.25)
    p75 = percentile(ordered, 0.75)
    return {
        "samples": len(ordered),
        "min": ordered[0],
        "p50": percentile(ordered, 0.50),
        "p90": percentile(ordered, 0.90),
        "p95": percentile(ordered, 0.95),
        "p99": percentile(ordered, 0.99),
        "max": ordered[-1],
        "iqr": p75 - p25,
        "unit": unit,
    }


def read_json_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events = []
    malformed = 0
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(event, dict) and "event" in event:
            events.append(event)
    return events, malformed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_presenter(path: Path) -> dict[str, Any]:
    events, malformed = read_json_events(path)
    profiles = [e for e in events if e.get("event") == "staging_profile"]
    stage_names = (
        "acquire_fence_wait_ns", "staging_pipeline_ns", "gbm_allocate_ns",
        "source_sync_start_ns", "source_map_ns", "destination_map_ns",
        "visible_copy_ns", "destination_unmap_ns", "source_unmap_ns",
        "source_sync_end_ns", "export_ns", "thread_cpu_ns",
        "acquire_wait_thread_cpu_ns", "voluntary_context_switches",
        "involuntary_context_switches", "minor_faults", "major_faults",
    )
    stages = {}
    for name in stage_names:
        vals = [int(e[name]) for e in profiles
                if isinstance(e.get(name), (int, float)) and e[name] >= 0]
        stages[name] = distribution(vals, "count" if "switches" in name or "faults" in name else "ns")
    # The legacy staging_copy event is emitted in both normal and detailed
    # tracing modes. It provides a comparable whole-pipeline duration for
    # measuring the incremental cost of the opt-in per-stage profile.
    legacy_staging_us = [int(e["overhead_us"]) for e in events
                         if e.get("event") == "staging_copy"
                         and isinstance(e.get("overhead_us"), (int, float))
                         and e["overhead_us"] >= 0]

    frame_events: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
    for event in events:
        if event.get("event") not in {
            "staging_profile", "staging_copy", "frame_committed", "frame_presented",
            "frame_discarded", "wayland_buffer_imported", "source_copy_complete",
            "transport_buffer_received",
        }:
            continue
        key = (int(event.get("generation", 0)), int(event.get("id", 0)))
        frame_events.setdefault(key, {})[str(event["event"])] = event
    commit_to_present = []
    copy_complete_to_commit = []
    received_to_staging_done = []
    for frame in frame_events.values():
        present = frame.get("frame_presented")
        if present and isinstance(present.get("commit_to_presentation_ns"), int):
            commit_to_present.append(present["commit_to_presentation_ns"])
        committed = frame.get("frame_committed")
        copy_done = frame.get("source_copy_complete")
        if committed and copy_done:
            copy_complete_to_commit.append(int(committed["t_ns"]) - int(copy_done["t_ns"]))
        received = frame.get("transport_buffer_received")
        staging_done = frame.get("staging_copy")
        if received and staging_done:
            received_to_staging_done.append(int(staging_done["t_ns"]) - int(received["t_ns"]))

    presentation = [e for e in events if e.get("event") == "frame_presented"
                    and isinstance(e.get("presentation_time_ns"), int)]
    unique_presentations = sorted({int(e["presentation_time_ns"]) for e in presentation})
    intervals = [b - a for a, b in zip(unique_presentations, unique_presentations[1:]) if b > a]
    refresh = [int(e["refresh_ns"]) for e in presentation
               if isinstance(e.get("refresh_ns"), int) and e["refresh_ns"] > 0]
    return {
        "path": str(path),
        "sha256": sha256(path),
        "event_count": len(events),
        "malformed_json_lines": malformed,
        "staging_profile_frames": len(profiles),
        "legacy_staging_timer_us": distribution(legacy_staging_us, "us"),
        "staging_stages": stages,
        "staging_pipeline_to_commit_ns": distribution(copy_complete_to_commit, "ns"),
        "receive_to_staging_event_ns": distribution(received_to_staging_done, "ns"),
        "commit_to_presentation_ns": distribution(commit_to_present, "ns"),
        "presentation_feedback": {
            "events": len(presentation),
            "clock_ids": sorted({e.get("presentation_clock_id") for e in presentation}),
            "clock_known": all(e.get("clock_id_known") is True for e in presentation),
            "presented_flags": sorted({e.get("flags") for e in presentation}),
            "refresh_ns": distribution(refresh, "ns"),
            "presentation_interval_ns": distribution(intervals, "ns"),
            "discarded_feedback_events": sum(e.get("event") == "frame_discarded" for e in events),
            "physical_scanout_claimed": False,
        },
        # Full frame events remain in the hash-addressed session logs. Keep
        # this report to distributions and aggregate counts so repeated runs
        # do not copy raw per-frame traces into the repository.
    }


def analyze_inputs(presenter_paths: list[Path], adapter_paths: list[Path]) -> dict[str, Any]:
    pointer_latencies = []
    key_latencies = []
    pairs = []
    for path, adapter_path in zip(presenter_paths, adapter_paths):
        events, _ = read_json_events(path)
        pointer_sent = {}
        keyboard_sent = {}
        for event in events:
            if event.get("event") == "input_sent":
                seq = event.get("sequence", event.get("id"))
                if isinstance(seq, int):
                    pointer_sent[seq] = event
            elif event.get("event") == "keyboard_packet_sent":
                seq = event.get("sequence", event.get("id"))
                if isinstance(seq, int):
                    keyboard_sent[seq] = event
        adapter_events, _ = read_json_events(adapter_path)
        adapter_done = {}
        for event in adapter_events:
            if event.get("event") in {"inject_done", "key_injected"}:
                seq = event.get("sequence")
                if isinstance(seq, int):
                    adapter_done[seq] = event
        pointer = 0
        keyboard = 0
        for seq, host in pointer_sent.items():
            done = adapter_done.get(seq)
            if not done:
                continue
            if "request_ns" in done and "done_ns" in done:
                delta = int(done["done_ns"]) - int(done["request_ns"])
                if delta >= 0:
                    pointer_latencies.append(delta)
                    pointer += 1
            elif isinstance(done.get("elapsed_ns"), (int, float)):
                # Auto backend's initial Binder capability probe logs elapsed
                # time rather than both monotonic endpoints.
                pointer_latencies.append(int(done["elapsed_ns"]))
                pointer += 1
        for seq, host in keyboard_sent.items():
            done = adapter_done.get(seq)
            if done and isinstance(done.get("t_ns"), int) and isinstance(host.get("t_ns"), int):
                # Both event timestamps use CLOCK_MONOTONIC; injection is
                # synchronous and key_injected is written after Binder returns.
                delta = int(done["t_ns"]) - int(host["t_ns"])
                if delta >= 0:
                    key_latencies.append(delta)
                    keyboard += 1
        pairs.append({"presenter_log": str(path), "adapter_log": str(adapter_path),
                      "matched_pointer": pointer, "matched_keyboard": keyboard})
    return {
        "clock_domain": "CLOCK_MONOTONIC; pointer request_ns is copied from the presenter packet, keyboard comparison uses both event t_ns values",
        "presenter_adapter_log_pairs": pairs,
        "pointer_packet_to_binder_injection_completion_ns": distribution(pointer_latencies, "ns"),
        "keyboard_packet_sent_to_binder_injection_completion_ns": distribution(key_latencies, "ns"),
        "input_to_affected_presentation": {
            "status": "not_measured",
            "reason": "No causal UI-state/frame marker is present in the accepted runtime logs; the next arbitrary presented frame is not proof of an input effect.",
        },
    }


def analyze(presenter_paths: list[Path], adapter_paths: list[Path] | None = None) -> dict[str, Any]:
    reports = [analyze_presenter(path) for path in presenter_paths]
    return {
        "schema_version": 1,
        "workstream": "Post-M1E Graphics Performance and Frame Pacing",
        "clock_domains": {
            "presenter_event_and_stage_timing": "CLOCK_MONOTONIC",
            "presenter_thread_active_time": "CLOCK_THREAD_CPUTIME_ID",
            "thread_faults_and_context_switches": "getrusage(RUSAGE_THREAD), interval deltas",
            "wayland_presentation": "wp_presentation.clock_id; timestamp kept separate from presenter event time",
            "cross_process": "No cross-process subtraction unless the component copied the presenter request timestamp into its event.",
        },
        "presenters": reports,
        "input": analyze_inputs(presenter_paths, adapter_paths or []),
        "claims": {
            "presentation_feedback_is_physical_photon_timestamp": False,
            "staging_pipeline_is_memcpy_only": False,
            "input_to_photon_measured": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--presenter-log", action="append", type=Path, required=True)
    parser.add_argument("--input-adapter-log", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    missing = [str(path) for path in [*args.presenter_log, *args.input_adapter_log] if not path.is_file()]
    if missing:
        parser.error("missing log(s): " + ", ".join(missing))
    result = analyze(args.presenter_log, args.input_adapter_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"analyzed {len(args.presenter_log)} presenter log(s) into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
