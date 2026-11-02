import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_graphics_performance import analyze, distribution


class GraphicsPerformanceAnalysisTests(unittest.TestCase):
    def test_distribution_reports_tail_and_sample_count(self):
        result = distribution([10, 20, 30, 100], "ns")
        self.assertEqual(result["samples"], 4)
        self.assertEqual(result["p50"], 20)
        self.assertEqual(result["max"], 100)
        self.assertEqual(result["iqr"], 20)

    def test_analyzes_staging_presentation_and_input_without_claiming_photons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            presenter = root / "presenter.log"
            adapter = root / "adapter.log"
            events = [
                {"t_ns": 100, "role": "presenter", "event": "staging_profile",
                 "generation": 2, "id": 4, "staging_pipeline_ns": 1000,
                 "visible_copy_ns": 300, "thread_cpu_ns": 400,
                 "voluntary_context_switches": 1, "involuntary_context_switches": 0},
                {"t_ns": 200, "role": "presenter", "event": "frame_committed",
                 "generation": 2, "id": 4},
                {"t_ns": 190, "role": "presenter", "event": "staging_copy",
                 "generation": 2, "id": 4, "overhead_us": 1},
                {"t_ns": 300, "role": "presenter", "event": "frame_presented",
                 "generation": 2, "id": 4, "presentation_time_ns": 500,
                 "refresh_ns": 16666667, "presentation_clock_id": 1,
                 "clock_id_known": True, "commit_to_presentation_ns": 200},
                {"t_ns": 400, "role": "presenter", "event": "input_sent",
                 "generation": 2, "id": 7, "sequence": 7},
                {"t_ns": 410, "role": "presenter", "event": "keyboard_packet_sent",
                 "generation": 2, "id": 8, "sequence": 8},
                {"t_ns": 411, "role": "presenter", "event": "keyboard_event_queued",
                 "generation": 2, "id": 8, "sequence": 8},
            ]
            presenter.write_text("".join(json.dumps(event) + "\n" for event in events))
            adapter.write_text("".join(json.dumps(event) + "\n" for event in [
                {"t_ns": 900, "event": "inject_done", "sequence": 7,
                 "request_ns": 600, "done_ns": 850},
                {"t_ns": 950, "event": "key_injected", "sequence": 8},
            ]))
            result = analyze([presenter], [adapter])
            report = result["presenters"][0]
            self.assertEqual(report["staging_stages"]["staging_pipeline_ns"]["p50"], 1000)
            self.assertEqual(report["commit_to_presentation_ns"]["p50"], 200)
            self.assertEqual(report["legacy_staging_timer_us"]["p50"], 1)
            self.assertEqual(result["input"]["pointer_packet_to_binder_injection_completion_ns"]["samples"], 1)
            self.assertEqual(result["input"]["keyboard_packet_sent_to_binder_injection_completion_ns"]["p50"], 540)
            self.assertFalse(result["claims"]["input_to_photon_measured"])
            self.assertEqual(result["input"]["input_to_affected_presentation"]["status"], "not_measured")

    def test_causal_input_response_requires_exact_presented_frame_and_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            presenter = root / "presenter.log"
            adapter = root / "adapter.log"
            events = [
                {"t_ns": 100, "event": "input_probe_started", "generation": 2,
                 "id": 7, "input_sequence": 7, "host_input_ns": 100,
                 "baseline_hash": "aaaa"},
                {"t_ns": 300, "event": "frame_committed", "generation": 2, "id": 9},
                {"t_ns": 400, "event": "input_probe_frame", "generation": 2, "id": 9,
                 "input_sequence": 7, "roi_valid": True, "changed": True,
                 "roi_hash": "bbbb", "baseline_hash": "aaaa"},
                {"t_ns": 500, "event": "frame_presented", "generation": 2, "id": 9,
                 "presentation_time_ns": 500, "presentation_clock_id": 1,
                 "clock_id_known": True, "refresh_ns": 16666667},
                {"t_ns": 501, "event": "input_response_presented", "generation": 2, "id": 9,
                 "input_sequence": 7, "host_input_ns": 100,
                 "presentation_time_ns": 500, "latency_ns": 400,
                 "presentation_clock_id": 1, "clock_valid": True,
                 "visual_change": True, "roi_hash": "bbbb", "baseline_hash": "aaaa"},
            ]
            presenter.write_text("".join(json.dumps(event) + "\n" for event in events))
            adapter.write_text(json.dumps({"t_ns": 150, "event": "inject_done",
                                           "sequence": 7, "request_ns": 100,
                                           "done_ns": 150, "rc": 0}) + "\n")
            result = analyze([presenter], [adapter])["input"]["input_to_affected_presentation"]
            self.assertEqual(result["status"], "measured")
            self.assertEqual(result["accepted_samples"], 1)
            self.assertEqual(result["latency_ns"]["p50"], 400)

            events[4]["presentation_clock_id"] = 2
            presenter.write_text("".join(json.dumps(event) + "\n" for event in events))
            result = analyze([presenter], [adapter])["input"]["input_to_affected_presentation"]
            self.assertEqual(result["accepted_samples"], 0)
            self.assertIn("frame feedback clock identity mismatch",
                          result["rejected_samples"][0]["reason"])

            events[4]["presentation_clock_id"] = 1
            events.extend([
                {"t_ns": 350, "event": "input_probe_frame", "generation": 2, "id": 8,
                 "input_sequence": 7, "roi_valid": True, "changed": True,
                 "roi_hash": "cccc", "baseline_hash": "aaaa"},
                {"t_ns": 360, "event": "frame_committed", "generation": 2, "id": 8},
                {"t_ns": 450, "event": "frame_presented", "generation": 2, "id": 8,
                 "presentation_time_ns": 450, "presentation_clock_id": 1,
                 "clock_id_known": True, "refresh_ns": 16666667},
            ])
            presenter.write_text("".join(json.dumps(event) + "\n" for event in events))
            result = analyze([presenter], [adapter])["input"]["input_to_affected_presentation"]
            self.assertEqual(result["accepted_samples"], 0)
            self.assertIn("not the first presented frame",
                          result["rejected_samples"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
