from __future__ import annotations

import unittest

from perf_skill.parser import build_request, parse_observation_statement, parse_statement


class ParseStatementTest(unittest.TestCase):
    def test_parse_chinese_statement(self) -> None:
        pid, comm, events = parse_statement("追踪 comm=python pid=4242 inst cycles")

        self.assertEqual(pid, 4242)
        self.assertEqual(comm, "python")
        self.assertEqual(events, ("instructions", "cycles"))

    def test_parse_chinese_statement_without_explicit_comm_key(self) -> None:
        pid, comm, events = parse_statement("追踪 node的 inst 和 cycles")

        self.assertIsNone(pid)
        self.assertEqual(comm, "node")
        self.assertEqual(events, ("instructions", "cycles"))

    def test_parse_chinese_event_aliases(self) -> None:
        pid, comm, events = parse_statement("追踪 node 的 指令 和 周期")

        self.assertIsNone(pid)
        self.assertEqual(comm, "node")
        self.assertEqual(events, ("instructions", "cycles"))

    def test_parse_statement_accepts_soft_and_tracepoint_events(self) -> None:
        pid, comm, events = parse_statement("追踪 node 的 cpu-clock 和 sched:sched_switch")

        self.assertIsNone(pid)
        self.assertEqual(comm, "node")
        self.assertEqual(
            events,
            ("instructions", "cycles", "cpu-clock", "sched:sched_switch"),
        )

    def test_parse_bare_target_tokens(self) -> None:
        pid, comm, events = parse_statement("observe nginx 31337 instructions")

        self.assertEqual(pid, 31337)
        self.assertEqual(comm, "nginx")
        self.assertEqual(events, ("instructions", "cycles"))

    def test_parse_freeform_chinese_statement_with_dry_run_hint(self) -> None:
        pid, comm, events = parse_statement("追踪 pid=4242 的 inst、cycles 和 cache-misses，先 dry-run")

        self.assertEqual(pid, 4242)
        self.assertIsNone(comm)
        self.assertEqual(
            events,
            (
                "instructions",
                "cycles",
                "cache-references",
                "cache-misses",
            ),
        )

    def test_parse_observation_statement_extracts_runtime_hints(self) -> None:
        parsed = parse_observation_statement(
            "追踪 pid=4242 的 inst、cycles 和 cache-misses，采样10次，先 dry-run"
        )

        self.assertEqual(parsed.pid, 4242)
        self.assertIsNone(parsed.comm)
        self.assertEqual(parsed.sample_count, 10)
        self.assertIsNone(parsed.duration_sec)
        self.assertTrue(parsed.wants_dry_run)
        self.assertEqual(
            parsed.events,
            (
                "instructions",
                "cycles",
                "cache-references",
                "cache-misses",
            ),
        )

    def test_parse_observation_statement_extracts_duration_hint(self) -> None:
        parsed = parse_observation_statement("observe comm=python inst cycles for 5 seconds")

        self.assertEqual(parsed.comm, "python")
        self.assertEqual(parsed.duration_sec, 5)
        self.assertIsNone(parsed.sample_count)

    def test_parse_observation_statement_detects_event_listing_request(self) -> None:
        parsed = parse_observation_statement("查看 cache 相关事件")

        self.assertTrue(parsed.wants_event_list)
        self.assertEqual(parsed.event_filters, ("cache",))
        self.assertEqual(parsed.events, ())

    def test_parse_observation_statement_handles_compact_chinese_duration(self) -> None:
        parsed = parse_observation_statement("我要追踪node20秒内的cycles")

        self.assertEqual(parsed.comm, "node")
        self.assertEqual(parsed.duration_sec, 20)
        self.assertEqual(parsed.events, ("instructions", "cycles"))

    def test_parse_observation_statement_handles_synonym_duration_and_samples(self) -> None:
        parsed = parse_observation_statement("追踪 node 持续 30 秒，采 20 个样本")

        self.assertEqual(parsed.comm, "node")
        self.assertEqual(parsed.duration_sec, 30)
        self.assertEqual(parsed.sample_count, 20)

    def test_parse_observation_statement_handles_branch_event_listing_synonym(self) -> None:
        parsed = parse_observation_statement("列出 branch 相关事件")

        self.assertTrue(parsed.wants_event_list)
        self.assertEqual(parsed.event_filters, ("branch",))

    def test_parse_observation_statement_handles_pmu_event_listing_synonym(self) -> None:
        parsed = parse_observation_statement("支持哪些 PMU 事件")

        self.assertTrue(parsed.wants_event_list)
        self.assertEqual(parsed.event_filters, ("pmu",))

    def test_parse_observation_statement_detects_svg_generation_request(self) -> None:
        parsed = parse_observation_statement("探测20秒node的cycles并生成图像")

        self.assertEqual(parsed.comm, "node")
        self.assertEqual(parsed.duration_sec, 20)
        self.assertTrue(parsed.wants_svg)
        self.assertEqual(parsed.events, ("instructions", "cycles"))

    def test_parse_observation_statement_detects_compact_svg_request(self) -> None:
        parsed = parse_observation_statement("生成10s内node的branchs的图像")

        self.assertEqual(parsed.comm, "node")
        self.assertEqual(parsed.duration_sec, 10)
        self.assertTrue(parsed.wants_svg)
        self.assertEqual(
            parsed.events,
            ("instructions", "cycles", "branches", "branch-misses"),
        )

    def test_parse_observation_statement_detects_perf_data_record_request(self) -> None:
        parsed = parse_observation_statement("追踪 node 的 cycles 并输出 perf.data")

        self.assertEqual(parsed.comm, "node")
        self.assertTrue(parsed.wants_perf_data)
        self.assertFalse(parsed.wants_parse_data)
        self.assertEqual(parsed.data_path, "perf.data")

    def test_parse_observation_statement_detects_perf_data_parse_request(self) -> None:
        parsed = parse_observation_statement("解析 out/node_targetpid4242_cycles_data_20260519T120000.data")

        self.assertTrue(parsed.wants_parse_data)
        self.assertFalse(parsed.wants_perf_data)
        self.assertEqual(
            parsed.data_path,
            "out/node_targetpid4242_cycles_data_20260519T120000.data",
        )

    def test_build_request_applies_event_override(self) -> None:
        request = build_request(
            "trace comm=python pid=4242 inst",
            pid=None,
            comm=None,
            extra_events=["cache-misses"],
            interval_ms=500,
            history_size=10,
        )

        self.assertEqual(
            request.events,
            ("instructions", "cycles", "cache-references", "cache-misses"),
        )
        self.assertEqual(request.interval_ms, 500)
        self.assertEqual(request.history_size, 10)

    def test_build_request_preserves_explicit_soft_and_tracepoint_events(self) -> None:
        request = build_request(
            "trace comm=python pid=4242 inst",
            pid=None,
            comm=None,
            extra_events=["cpu-clock", "sched:sched_switch", "cache-misses"],
            interval_ms=500,
            history_size=10,
        )

        self.assertEqual(
            request.events,
            (
                "instructions",
                "cycles",
                "cpu-clock",
                "sched:sched_switch",
                "cache-references",
                "cache-misses",
            ),
        )

    def test_parse_statement_completes_event_pairs(self) -> None:
        pid, comm, events = parse_statement("observe nginx 31337 branch-misses cache-misses")

        self.assertEqual(pid, 31337)
        self.assertEqual(comm, "nginx")
        self.assertEqual(
            events,
            (
                "instructions",
                "cycles",
                "branches",
                "branch-misses",
                "cache-references",
                "cache-misses",
            ),
        )


if __name__ == "__main__":
    unittest.main()
