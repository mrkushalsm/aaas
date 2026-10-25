#!/usr/bin/env python3
"""Check observed ownership on a bounded real-compositor trace."""
import json
import sys
from collections import Counter


def check(path):
    busy = set()
    seen = Counter()
    summary = None
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            name = event["event"]
            key = (event.get("generation"), event.get("id"))
            seen[name] += 1
            if name == "frame_sent_cpu_write":
                assert key not in busy, f"reused before release: {key}"
                busy.add(key)
            elif name == "release" and event.get("role") == "producer":
                assert key in busy, f"unknown release: {key}"
                busy.remove(key)
            elif name == "summary":
                summary = event
    assert seen["dmabuf_import_submit"] > 5, "no sustained imports"
    assert seen["wl_buffer_release"] > 3, "no compositor releases"
    assert seen["frame_sent_cpu_write"] > 5, "no changing producer frames"
    assert summary and summary["imports"] == seen["dmabuf_import_submit"]
    assert summary["releases"] == seen["wl_buffer_release"]
    print(f"trace verified: {seen['dmabuf_import_submit']} imports, "
          f"{seen['wl_buffer_release']} compositor releases")


if __name__ == "__main__":
    check(sys.argv[1])
