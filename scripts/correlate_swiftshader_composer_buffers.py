#!/usr/bin/env python3
"""Join diagnostic SwiftShader AHardwareBuffer records to Composer frames.

The stable AaaS allocator buffer ID is the primary join key. FD device/inode
and geometry are corroborating metadata; timestamps and dimensions alone are
never treated as proof of identity.
"""

import argparse
import json
from pathlib import Path
import re


FIELD = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")


def fields(line):
    return {key: value for key, value in FIELD.findall(line)}


def number(record, key):
    value = record.get(key)
    if value is None:
        return None
    return int(value, 0)


def read_composer(path):
    records = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if ("AAAS_COMPOSER_FRAME" not in line and
                "virtual output frame" not in line):
            continue
        row = fields(line)
        required = ("display", "slot", "generation", "buffer_id", "width",
                    "height", "stride")
        if all(key in row for key in required):
            records.append({key: number(row, key) for key in required} | {
                "dma_dev": number(row, "dma_dev"),
                "dma_ino": number(row, "dma_ino"),
            })
    return records


def read_swiftshader(path):
    records = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if "AAAS_AHB_VK_IMPORT" not in line:
            continue
        row = fields(line)
        if "buffer_id" not in row:
            continue
        records.append({key: number(row, key) for key in (
            "pid", "tid", "mono_ns", "id", "buffer_id", "dma_dev",
            "dma_ino", "memory_id", "width", "height", "stride",
        ) if key in row} | {"base": row.get("base")})
    return records


def read_draws(path):
    events = []
    for line in Path(path).read_text(errors="replace").splitlines():
        kind_match = re.search(r"\b(AAAS_DRAW_[A-Z_]+|AAAS_JIT_ENTRY)\b", line)
        if not kind_match:
            continue
        row = fields(line)
        row["event"] = kind_match.group(1)
        for key in ("pid", "tid", "mono_ns", "id", "submit_id", "draw_id",
                    "pipeline_id", "memory_id", "image_id", "view_id"):
            if key in row:
                row[key] = number(row, key)
        events.append(row)
    return events


def correlate(swiftshader, composer):
    by_id = {}
    for frame in composer:
        if frame["buffer_id"]:
            by_id.setdefault(frame["buffer_id"], []).append(frame)
    joined = []
    unmatched = []
    for allocation in swiftshader:
        sightings = by_id.get(allocation.get("buffer_id"), [])
        if not sightings:
            unmatched.append(allocation)
            continue
        for frame in sightings:
            same_fd_identity = (
                allocation.get("dma_dev") is not None and
                allocation.get("dma_ino") not in (None, 0) and
                allocation.get("dma_dev") == frame.get("dma_dev") and
                allocation.get("dma_ino") == frame.get("dma_ino")
            )
            same_geometry = all(allocation.get(key) == frame.get(key)
                                for key in ("width", "height", "stride"))
            joined.append({"buffer_id": allocation["buffer_id"],
                           "swiftshader": allocation,
                           "composer": frame,
                           "stable_buffer_id_match": True,
                           "fd_identity_match": same_fd_identity,
                           "geometry_match": same_geometry})
    return {"schema_version": 1, "join_policy": "stable_allocator_buffer_id",
            "matches": joined, "unmatched_swiftshader": unmatched,
            "composer_frame_count": len(composer),
            "swiftshader_import_count": len(swiftshader)}


def correlate_draw_resources(events, ahb_imports, composer):
    """Join target draws to imports by process-local memory ID, then buffer ID."""
    ahb_by_memory = {}
    for allocation in ahb_imports:
        if allocation.get("memory_id") is not None:
            ahb_by_memory.setdefault(allocation["memory_id"], []).append(allocation)
    composer_by_id = {}
    for frame in composer:
        if frame["buffer_id"]:
            composer_by_id.setdefault(frame["buffer_id"], []).append(frame)

    by_draw = {}
    for event in events:
        if "submit_id" not in event or "draw_id" not in event:
            continue
        by_draw.setdefault((event["submit_id"], event["draw_id"]), []).append(event)

    results = []
    for key, group in by_draw.items():
        target = next((event for event in group
                       if event["event"] == "AAAS_DRAW_TARGET"), None)
        work = next((event for event in group
                     if event["event"] == "AAAS_DRAW_WORK_BEGIN"), None)
        complete = next((event for event in group
                         if event["event"] == "AAAS_DRAW_COMPLETE"), None)
        if target is None or work is None or "memory_id" not in target:
            continue
        routines = [event for event in events
                    if event["event"] == "AAAS_JIT_ENTRY" and
                    event.get("address") == work.get("pixel_routine")]
        for allocation in ahb_by_memory.get(target["memory_id"], []):
            frames = composer_by_id.get(allocation.get("buffer_id"), [])
            results.append({
                "submit_id": key[0], "draw_id": key[1],
                "pipeline_id": target.get("pipeline_id"),
                "view_id": target.get("view_id"),
                "image_id": target.get("image_id"),
                "memory_id": target.get("memory_id"),
                "target_base": target.get("base"),
                "pixel_routine": work.get("pixel_routine"),
                "jit_routine_matches": routines,
                "draw_completion_observed": complete is not None,
                "ahardwarebuffer": allocation,
                "composer_frames": frames,
            })
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--swiftshader", type=Path, required=True)
    parser.add_argument("--composer", type=Path, required=True)
    parser.add_argument("--include-draws", action="store_true",
                        help="also join draw targets to AHardwareBuffer and Composer IDs")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = correlate(read_swiftshader(args.swiftshader),
                       read_composer(args.composer))
    if args.include_draws:
        imports = read_swiftshader(args.swiftshader)
        composer_records = read_composer(args.composer)
        result["draw_resource_correlations"] = correlate_draw_resources(
            read_draws(args.swiftshader), imports, composer_records)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
