from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from perf_skill.analysis import parse_perf_script_line, render_observation_summary, render_perf_data_summary, summarize_perf_script_output, summarize_samples, write_summary_json
from perf_skill.models import ObservationRequest, PerfSample, TargetProcess


class AnalysisHelpersTest(unittest.TestCase):
    def test_summarize_samples_renders_metrics_and_ratios(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles branches",
            pid=4242,
            comm="node",
            events=("instructions", "cycles", "branches", "branch-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="node")
        samples = [
            PerfSample(
                timestamp_sec=10.0,
                values={"instructions": 1000.0, "cycles": 2000.0, "branches": 100.0, "branch-misses": 3.0},
                ipc=0.5,
            ),
            PerfSample(
                timestamp_sec=12.0,
                values={"instructions": 1500.0, "cycles": 2400.0, "branches": 120.0, "branch-misses": 6.0},
                ipc=0.625,
            ),
        ]

        summary = summarize_samples(request, target, samples)
        rendered = render_observation_summary(summary)

        self.assertEqual(summary.sample_count, 2)
        self.assertEqual(summary.duration_sec, 2.0)
        self.assertIn("metric    : instructions avg=1.25K peak=1.50K last=1.50K trend=rising", rendered)
        self.assertIn("metric    : ipc avg=0.562 peak=0.625 last=0.625 trend=rising", rendered)
        self.assertIn("derived   : branch-miss-rate=4.09%", rendered)

    def test_parse_perf_script_line(self) -> None:
        record = parse_perf_script_line(
            "node 4242/4242 [002] 123.456: cycles: 7f00abcd v8::Function+0x10 (node)"
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.comm, "node")
        self.assertEqual(record.pid, 4242)
        self.assertEqual(record.tid, 4242)
        self.assertEqual(record.cpu, 2)
        self.assertEqual(record.time_sec, 123.456)
        self.assertEqual(record.event, "cycles")
        self.assertEqual(record.symbol, "v8::Function+0x10")
        self.assertEqual(record.dso, "node")

    def test_summarize_perf_script_output_renders_top_sections(self) -> None:
        script_output = "\n".join(
            [
                "node 4242/4242 [002] 123.456: cycles: 7f00abcd v8::Function+0x10 (node)",
                "node 4242/4242 [002] 123.556: cycles: 7f00abce v8::Function+0x10 (node)",
                "node 4242/4242 [002] 123.656: sched:sched_switch: finish_task_switch+0x1 ([kernel.kallsyms])",
            ]
        )

        summary = summarize_perf_script_output("out/node.data", script_output)
        rendered = render_perf_data_summary(summary)

        self.assertEqual(summary.sample_count, 3)
        self.assertAlmostEqual(summary.duration_sec, 0.2)
        self.assertIn("top-event : cycles=2", rendered)
        self.assertIn("top-comm  : node=3", rendered)
        self.assertIn("top-sym   : v8::Function+0x10 [node]=2", rendered)

    def test_write_summary_json(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles",
            pid=4242,
            comm="node",
            events=("instructions", "cycles"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="node")
        summary = summarize_samples(
            request,
            target,
            [
                PerfSample(
                    timestamp_sec=10.0,
                    values={"instructions": 1000.0, "cycles": 2000.0},
                    ipc=0.5,
                )
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "summary.json"
            write_summary_json(str(output_path), summary)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["pid"], 4242)
        self.assertEqual(payload["comm"], "node")
        self.assertEqual(payload["metrics"][0]["name"], "instructions")


if __name__ == "__main__":
    unittest.main()