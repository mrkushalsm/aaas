import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_staged_mixed_session import analyze


def _event(name, t_ns, **fields):
    return {"role": "presenter", "event": name, "t_ns": t_ns, **fields}


class StagedMixedSessionEvidenceTests(unittest.TestCase):
    def make_session(self, mutate=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "status").write_text("STOPPED\n")
        (root / "state.jsonl").write_text(
            '{"state":"RUNNING"}\n{"state":"STOPPED"}\n'
        )
        (root / "logcat.log").write_text("system_server and SurfaceFlinger healthy\n")
        (root / "ipc").mkdir()
        (root / "ipc" / "display_broker.log").write_text(
            "created index=0 displayId=2\ncreated index=1 displayId=3\n"
        )
        composer = root / "composer.log"
        composer.write_text(
            "[AaasComposerClient] createVirtualDisplay id=100 size=720x1280 slots=1 format=1\n"
            "[AaasComposerClient] createVirtualDisplay id=101 size=720x1280 slots=1 format=1\n"
            "[AaasComposerClient] virtual output frame display=100 slot=0 generation=1 buffer_id=10 width=720 height=1280 stride=720 dma_dev=1 dma_ino=1001 command=0\n"
            "[AaasComposerClient] virtual output frame display=101 slot=0 generation=1 buffer_id=20 width=720 height=1280 stride=720 dma_dev=1 dma_ino=2001 command=0\n"
            "[AaasComposerClient] mixed-frame verify display=100 layer=9 src_id=1 dst_id=10 layer_id=11 src=1:9001 dst=1:1001 overlay=1:9101 pixels=exact\n"
            "[AaasComposerClient] mixed-frame verify display=101 layer=19 src_id=2 dst_id=20 layer_id=21 src=1:9002 dst=1:2001 overlay=1:9102 pixels=exact\n"
        )
        for number, source, stage in ((1, 1001, 1101), (2, 2001, 2101)):
            filename = "virtual-presenter.log" if number == 1 else "virtual-presenter2.log"
            events = [
                _event("transport_buffer_received", 10, generation=1, id=1, dma_dev=1,
                       dma_ino=source, fstat_ok=True),
                _event("staging_copy", 20, generation=1, id=1, overhead_us=5),
                _event("source_copy_complete", 30, generation=1, id=1),
                _event("wayland_buffer_imported", 40, generation=1, id=1, dma_dev=1,
                       dma_ino=stage, fstat_ok=True, staged_copy=True),
                _event("frame_committed", 50, generation=1, id=1, explicit_sync=True),
                _event("buffer_release", 60, generation=1, id=1),
                _event("summary", 70, generation=1, id=0, imports=1, submissions=1,
                       releases=1, rejected=0, presented=1, discarded=0, input_sent=1,
                       input_dropped=0, outstanding=0, teardown_invalidated=0,
                       maxrss_kib=1000),
            ]
            if mutate:
                mutate(number, events)
            (root / filename).write_text("".join(json.dumps(event) + "\n" for event in events))
        return temp, root, composer

    def test_accepts_two_distinct_mixed_outputs_and_staged_wayland_buffers(self):
        temp, root, composer = self.make_session()
        with temp:
            result = analyze(root, composer, "default")
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(len(result["presenter_output_correlations"]), 2)
        self.assertEqual(result["presenters"][0]["summary"]["outstanding"], 0)
        sample = result["presenters"][0]["staged_frame_identity_samples"][0]
        self.assertNotEqual(sample["composer_output_backing"], sample["wayland_staging_backing"])
        self.assertLessEqual(sample["frame_commit_ns"], sample["wayland_release_ns"])

    def test_rejects_aliasing_staging_allocation(self):
        def alias_stage(slot, events):
            if slot == 1:
                events[3]["dma_ino"] = 1001
        temp, root, composer = self.make_session(alias_stage)
        with temp:
            with self.assertRaisesRegex(ValueError, "reused Composer output"):
                analyze(root, composer, "default")

    def test_rejects_copy_completion_after_wayland_commit(self):
        def reorder(slot, events):
            if slot == 2:
                events[2]["t_ns"] = 100
        temp, root, composer = self.make_session(reorder)
        with temp:
            with self.assertRaisesRegex(ValueError, "copy/commit/release order"):
                analyze(root, composer, "enhanced")

    def test_rejects_wayland_release_before_commit(self):
        def premature_release(slot, events):
            if slot == 2:
                events[5]["t_ns"] = 45
        temp, root, composer = self.make_session(premature_release)
        with temp:
            with self.assertRaisesRegex(ValueError, "copy/commit/release order"):
                analyze(root, composer, "default")

    def test_rejects_missing_wayland_release_event(self):
        def omit_release(slot, events):
            if slot == 1:
                events.pop(5)
        temp, root, composer = self.make_session(omit_release)
        with temp:
            with self.assertRaisesRegex(ValueError, "lacks copy/commit/release"):
                analyze(root, composer, "default")

    def test_rejects_unbalanced_presenter_ownership(self):
        def leak(slot, events):
            if slot == 1:
                events[-1]["outstanding"] = 1
        temp, root, composer = self.make_session(leak)
        with temp:
            with self.assertRaisesRegex(ValueError, "did not release all"):
                analyze(root, composer, "default")

    def test_aggregates_presenter_close_and_reopen_lifecycles(self):
        def append_empty_lifecycle(slot, events):
            summary = dict(events[-1])
            summary.update({
                "t_ns": 80,
                "imports": 0,
                "submissions": 0,
                "releases": 0,
                "presented": 0,
                "discarded": 0,
                "input_sent": 0,
                "input_dropped": 0,
                "outstanding": 0,
                "teardown_invalidated": 0,
            })
            events.append(summary)

        temp, root, composer = self.make_session(append_empty_lifecycle)
        with temp:
            result = analyze(root, composer, "enhanced")
        self.assertEqual(result["presenters"][0]["summary"]["presenter_lifecycles"], 2)
        self.assertEqual(result["presenters"][0]["summary"]["imports"], 1)


if __name__ == "__main__":
    unittest.main()
