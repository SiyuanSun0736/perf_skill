from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from perf_skill.analysis import parse_perf_script_line, parse_perf_script_records, render_observation_summary, render_perf_data_summary, summarize_perf_script_output, summarize_samples, write_summary_json
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
        self.assertIn("insight   : CPU throughput is low; average IPC is 0.562", rendered)
        self.assertNotIn("explain   :", rendered)
        self.assertIn("next-step : capture call stacks with perf record -g -p 4242 -- sleep 15", rendered)

    def test_summarize_samples_detects_ipc_drop_and_miss_rate_surge(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles branches branch-misses",
            pid=4242,
            comm="node",
            events=("instructions", "cycles", "branches", "branch-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="node")
        samples = [
            PerfSample(
                timestamp_sec=1.0,
                values={"instructions": 1000.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0},
                ipc=1.0,
            ),
            PerfSample(
                timestamp_sec=2.0,
                values={"instructions": 980.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0},
                ipc=0.98,
            ),
            PerfSample(
                timestamp_sec=3.0,
                values={"instructions": 400.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 18.0},
                ipc=0.4,
            ),
        ]

        summary = summarize_samples(request, target, samples)
        rendered = render_observation_summary(summary)

        self.assertEqual(len(summary.anomalies), 2)
        self.assertIn("anomaly   : at=3.00s ipc drop baseline=0.990 current=0.400 delta=-59.6%", rendered)
        self.assertIn("anomaly   : at=3.00s branch-miss-rate surge baseline=2.00% current=18.00% delta=+800.0%", rendered)
        self.assertIn("insight   : Branch prediction is unstable; branch-miss-rate reached 18.00%", rendered)
        self.assertIn("insight   : The stall is bursty rather than constant; The first anomaly appears at 3.00s", rendered)

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
        self.assertEqual(record.callchain, ())

    def test_parse_perf_script_records_collects_indented_callchain_block(self) -> None:
        script_output = "\n".join(
            [
                "node 4242/4242 [002] 123.456: cycles:",
                "        7f00abcd v8::Function+0x10 (node)",
                "        7f00abce main (node)",
            ]
        )

        records = parse_perf_script_records(script_output)

        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].callchain,
            ("v8::Function+0x10 [node]", "main [node]"),
        )
        self.assertEqual(records[0].symbol, "v8::Function+0x10")
        self.assertEqual(records[0].dso, "node")

    def test_summarize_perf_script_output_renders_top_sections(self) -> None:
        script_output = "\n".join(
            [
                "node 4242/4242 [002] 123.456: cycles:",
                "        7f00abcd v8::Function+0x10 (node)",
                "        7f00aaaa main (node)",
                "node 4242/4242 [002] 123.556: cycles:",
                "        7f00abce v8::Function+0x10 (node)",
                "        7f00aaaa main (node)",
                "node 4242/4243 [002] 123.606: cycles:",
                "        7f00abcf v8::Other+0x10 (node)",
                "        7f00aaaa main (node)",
                "node 4242/4242 [002] 123.656: sched:sched_switch:",
                "        ffffffff8107b6d7 finish_task_switch+0x147 ([kernel.kallsyms])",
                "        ffffffff8106ffff __schedule+0x3ff ([kernel.kallsyms])",
            ]
        )

        summary = summarize_perf_script_output("out/node.data", script_output)
        rendered = render_perf_data_summary(summary)

        self.assertEqual(summary.sample_count, 4)
        self.assertAlmostEqual(summary.duration_sec, 0.2)
        self.assertIn("top-event : cycles=3", rendered)
        self.assertIn("top-comm  : node=4", rendered)
        self.assertIn("top-thread: node pid=4242 tid=4242=3", rendered)
        self.assertIn("top-callchain: v8::Function+0x10 [node] <- main [node]=2", rendered)
        self.assertIn("top-callchain[cycles]: v8::Function+0x10 [node] <- main [node]=2", rendered)
        self.assertIn("top-callchain[sched:sched_switch]: finish_task_switch+0x147 [[kernel.kallsyms]] <- __schedule+0x3ff [[kernel.kallsyms]]=1", rendered)
        self.assertIn("top-sym   : v8::Function+0x10 [node]=2", rendered)
        self.assertIn("hotspot   : v8::Function+0x10 [node] samples=2 share=50.00%", rendered)
        self.assertIn("insight   : One symbol dominates the recorded time; v8::Function+0x10 [node] accounts for 50.00% of parsed samples", rendered)
        self.assertIn("next-step : Inspect it with perf annotate --stdio -i out/node.data --symbol 'v8::Function+0x10'.", rendered)
        self.assertEqual(
            summary.event_callchain_counts,
            (
                (
                    "cycles",
                    (
                        ("v8::Function+0x10 [node] <- main [node]", 2),
                        ("v8::Other+0x10 [node] <- main [node]", 1),
                    ),
                ),
                (
                    "sched:sched_switch",
                    (
                        (
                            "finish_task_switch+0x147 [[kernel.kallsyms]] <- __schedule+0x3ff [[kernel.kallsyms]]",
                            1,
                        ),
                    ),
                ),
            ),
        )

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
        self.assertEqual(payload["insights"][0]["category"], "low-ipc")
        self.assertNotIn("plain_language", payload["insights"][0])


if __name__ == "__main__":
    unittest.main()