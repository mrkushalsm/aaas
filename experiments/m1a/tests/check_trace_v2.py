#!/usr/bin/env python3
"""Validate an observed execution trace from AaaS M1A.1 GPU Explicit Synchronization."""

import json
import sys
from collections import Counter


def check_trace(trace_path: str):
    seen = Counter()
    busy_buffers = set()
    released_fences = set()
    summary = None
    last_acquire_point = 0

    with open(trace_path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            role = event.get("role")
            ev_name = event.get("event")
            gen = event.get("generation")
            buf_id = event.get("id")
            key = (gen, buf_id)
            seen[ev_name] += 1

            if ev_name == "capabilities":
                assert event.get("explicit_sync_capable") is True, "presenter must be explicit_sync_capable"

            elif ev_name == "gpu_initialized":
                assert event.get("renderer") == "GLES2"
                assert event.get("fence_extension") == "EGL_ANDROID_native_fence_sync"

            elif ev_name == "frame_sent_gpu":
                assert event.get("explicit_sync") is True, f"frame must have explicit sync: {event}"
                assert key not in busy_buffers, f"Buffer {key} sent while still busy!"
                busy_buffers.add(key)

            elif ev_name == "frame_committed":
                assert event.get("explicit_sync") is True
                acq_pt = event.get("acquire_point")
                assert acq_pt > last_acquire_point, f"acquire_point must increase: {acq_pt} <= {last_acquire_point}"
                last_acquire_point = acq_pt

            elif ev_name == "release_with_fence":
                assert event.get("fence") == "received"
                assert key in busy_buffers, f"release for non-busy buffer {key}"
                released_fences.add(key)

            elif ev_name == "release_fence_waited":
                assert key in released_fences, f"waited on fence for unreleased buffer {key}"
                assert event.get("release_wait_result") == 1, "release fence wait must succeed"
                busy_buffers.remove(key)
                released_fences.remove(key)

            elif ev_name == "summary":
                summary = event

    assert summary is not None, "trace missing summary event"
    assert summary["explicit_sync_frames"] > 0, "no explicit sync frames recorded"
    assert summary["submissions"] == summary["imports"]
    assert summary["rejected"] == 0, f"unexpected rejected frames: {summary['rejected']}"
    assert seen["frame_sent_gpu"] >= 5, "insufficient GPU frames"
    assert seen["frame_presented"] >= 3, "insufficient presentation events"

    print(f"Trace verified successfully: {summary['submissions']} GPU submissions, "
          f"{summary['explicit_sync_frames']} explicit-sync frames, "
          f"{summary['releases']} releases, {summary['presented']} presented.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_trace_v2.py <path/to/trace.jsonl>", file=sys.stderr)
        sys.exit(1)
    check_trace(sys.argv[1])
