from __future__ import annotations

import unittest
from unittest.mock import patch

from perf_skill.models import ObservationRequest, PerfSample, PerfStatError, TargetProcess
from perf_skill.perf import build_perf_command, build_perf_record_command, build_perf_script_command, build_retry_plans, detect_pmu_slot_limit, format_retry_plan, parse_perf_csv_line, parse_perf_status_line, plan_event_groups, stream_perf_samples


class PerfHelpersTest(unittest.TestCase):
    def test_build_perf_command(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles",
            pid=4242,
            comm="python",
            events=("instructions", "cycles"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")

        command = build_perf_command(request, target, pmu_slots=4)

        self.assertEqual(
            command,
            [
                "perf",
                "stat",
                "--interval-print",
                "1000",
                "--no-big-num",
                "-x",
                ",",
                "-e",
                "{instructions,cycles}",
                "-p",
                "4242",
            ],
        )

    def test_build_perf_command_group_off(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles cache-misses",
            pid=4242,
            comm="python",
            events=("instructions", "cycles", "cache-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")

        command = build_perf_command(request, target, group_mode="off", pmu_slots=4)

        self.assertEqual(command[8], "instructions,cycles,cache-misses")

    def test_build_perf_record_command(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles",
            pid=4242,
            comm="python",
            events=("instructions", "cycles"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")

        command = build_perf_record_command(
            request,
            target,
            output_path="out/python_targetpid4242_cycles_data_20260519T120000.data",
            duration_sec=10,
            pmu_slots=4,
        )

        self.assertEqual(
            command,
            [
                "perf",
                "record",
                "-o",
                "out/python_targetpid4242_cycles_data_20260519T120000.data",
                "-e",
                "{instructions,cycles}",
                "-p",
                "4242",
                "--",
                "sleep",
                "10",
            ],
        )

    def test_build_perf_script_command(self) -> None:
        self.assertEqual(
            build_perf_script_command("out/node_targetpid4242_cycles_data_20260519T120000.data"),
            ["perf", "script", "-i", "out/node_targetpid4242_cycles_data_20260519T120000.data"],
        )

    def test_plan_event_groups_auto(self) -> None:
        groups = plan_event_groups(
            ("instructions", "cycles", "cache-misses", "branches", "branch-misses"),
            group_mode="auto",
            pmu_slots=4,
        )

        self.assertEqual(
            groups,
            (("instructions", "cycles", "cache-misses"), ("branches", "branch-misses")),
        )

    def test_plan_event_groups_respects_pmu_slots(self) -> None:
        groups = plan_event_groups(
            (
                "instructions",
                "cycles",
                "cache-references",
                "cache-misses",
                "branches",
                "branch-misses",
            ),
            group_mode="auto",
            pmu_slots=2,
        )

        self.assertEqual(
            groups,
            (
                ("instructions", "cycles"),
                ("branches", "branch-misses"),
                ("cache-references", "cache-misses"),
            ),
        )

    def test_detect_pmu_slot_limit_defaults_to_four(self) -> None:
        self.assertEqual(detect_pmu_slot_limit(), 4)

    def test_plan_event_groups_ignores_software_and_tracepoint_slot_cost(self) -> None:
        groups = plan_event_groups(
            (
                "instructions",
                "cycles",
                "cache-references",
                "cache-misses",
                "cpu-clock",
                "sched:sched_switch",
                "branches",
                "branch-misses",
            ),
            group_mode="auto",
            pmu_slots=4,
        )

        self.assertEqual(
            groups,
            (
                ("instructions", "cycles", "cpu-clock", "sched:sched_switch"),
                ("branches", "branch-misses"),
                ("cache-references", "cache-misses"),
            ),
        )

    def test_plan_event_groups_prefers_same_prefix_names(self) -> None:
        groups = plan_event_groups(
            (
                "instructions",
                "cycles",
                "branches",
                "branch-misses",
                "branch-loads",
            ),
            group_mode="auto",
            pmu_slots=4,
        )

        self.assertEqual(
            groups,
            (
                ("instructions", "cycles"),
                ("branches", "branch-misses", "branch-loads"),
            ),
        )

    def test_plan_event_groups_prefers_same_cache_prefix_names(self) -> None:
        groups = plan_event_groups(
            (
                "instructions",
                "cycles",
                "cache-references",
                "cache-misses",
                "cache-prefetches",
            ),
            group_mode="auto",
            pmu_slots=4,
        )

        self.assertEqual(
            groups,
            (
                ("instructions", "cycles"),
                ("cache-references", "cache-misses", "cache-prefetches"),
            ),
        )

    def test_parse_perf_csv_line(self) -> None:
        measurement = parse_perf_csv_line(
            "1.000123,123456,,instructions,100.00,",
            ("instructions", "cycles"),
        )

        self.assertIsNotNone(measurement)
        assert measurement is not None
        self.assertEqual(measurement.event, "instructions")
        self.assertEqual(measurement.value, 123456.0)

    def test_parse_perf_status_line(self) -> None:
        status = parse_perf_status_line(
            "1.001075428,<not counted>,,cycles:u,0,100.00,,",
            ("instructions", "cycles"),
        )

        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.event, "cycles")
        self.assertEqual(status.status, "not counted")

    def test_parse_perf_csv_line_matches_tracepoint_event(self) -> None:
        measurement = parse_perf_csv_line(
            "1.500000,7,,sched:sched_switch,100.00,",
            ("instructions", "cycles", "sched:sched_switch"),
        )

        self.assertIsNotNone(measurement)
        assert measurement is not None
        self.assertEqual(measurement.event, "sched:sched_switch")
        self.assertEqual(measurement.value, 7.0)

    def test_build_retry_plans(self) -> None:
        plans = build_retry_plans(group_mode="auto", pmu_slots=4, retry_grouping=True)

        self.assertEqual(
            [(plan.group_mode, plan.pmu_slots) for plan in plans],
            [("auto", 4), ("auto", 2), ("auto", 1), ("off", 1)],
        )
        self.assertEqual(format_retry_plan(plans), "auto/4 -> auto/2 -> auto/1 -> off/1")

    def test_stream_perf_samples_retries_with_smaller_groups(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles branches",
            pid=4242,
            comm="python",
            events=("instructions", "cycles", "branches"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        sample = PerfSample(
            timestamp_sec=1.0,
            values={
                "instructions": 1000.0,
                "cycles": 2000.0,
                "branches": 300.0,
            },
            ipc=0.5,
        )
        attempts: list[tuple[str, ...]] = []

        def fake_stream_attempt(request, target, *, groups=None, stop_event=None):
            attempts.append(request.events)
            if request.events == ("instructions", "cycles", "branches"):
                raise PerfStatError(
                    "uncounted grouped events",
                    kind="unsupported_events",
                    diagnostics=("<not counted>",),
                    unsupported_events={"instructions": "not counted"},
                )
            return iter([sample])

        with patch("perf_skill.perf._stream_perf_attempt", side_effect=fake_stream_attempt):
            samples = list(stream_perf_samples(request, target, group_mode="auto", pmu_slots=4))

        self.assertEqual(
            attempts,
            [
                ("instructions", "cycles", "branches"),
                ("instructions", "cycles"),
                ("branches",),
            ],
        )
        self.assertEqual(samples, [sample])

    def test_stream_perf_samples_runs_initial_groups_in_single_attempt(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles cache-misses branches",
            pid=4242,
            comm="python",
            events=(
                "instructions",
                "cycles",
                "cache-references",
                "cache-misses",
                "branches",
                "branch-misses",
            ),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        attempts: list[tuple[tuple[str, ...] | None, tuple[str, ...]]] = []
        sample = PerfSample(
            timestamp_sec=1.0,
            values={
                "instructions": 1000.0,
                "cycles": 2000.0,
                "cache-references": 500.0,
                "cache-misses": 200.0,
                "branches": 300.0,
                "branch-misses": 10.0,
            },
            ipc=0.5,
        )

        def fake_stream_attempt(request, target, *, groups=None, stop_event=None):
            attempts.append((groups, request.events))
            return iter([sample])

        with patch("perf_skill.perf._stream_perf_attempt", side_effect=fake_stream_attempt):
            samples = list(stream_perf_samples(request, target, group_mode="auto", pmu_slots=2))

        self.assertEqual(samples, [sample])
        self.assertEqual(
            attempts,
            [
                (
                    (
                        ("instructions", "cycles"),
                        ("branches", "branch-misses"),
                        ("cache-references", "cache-misses"),
                    ),
                    (
                        "instructions",
                        "cycles",
                        "cache-references",
                        "cache-misses",
                        "branches",
                        "branch-misses",
                    ),
                )
            ],
        )

    def test_stream_perf_samples_only_splits_failed_group(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles cache-misses",
            pid=4242,
            comm="python",
            events=("instructions", "cycles", "cache-references", "cache-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        attempted_groups: list[tuple[tuple[str, ...] | None, tuple[str, ...]]] = []

        def fake_stream_attempt(request, target, *, groups=None, stop_event=None):
            attempted_groups.append((groups, request.events))
            if groups == (("instructions", "cycles"), ("cache-references", "cache-misses")):
                raise PerfStatError(
                    "combined grouped run failed",
                    kind="process_exit",
                    diagnostics=("too many events",),
                )
            if request.events == ("instructions", "cycles"):
                return iter([
                    PerfSample(
                        timestamp_sec=1.0,
                        values={"instructions": 1000.0, "cycles": 2000.0},
                        ipc=0.5,
                    )
                ])
            if request.events == ("cache-references", "cache-misses"):
                raise PerfStatError(
                    "uncounted grouped events",
                    kind="unsupported_events",
                    diagnostics=("<not counted>",),
                    unsupported_events={"cache-references": "not counted"},
                )
            if request.events == ("cache-references",):
                return iter([
                    PerfSample(
                        timestamp_sec=1.0,
                        values={"cache-references": 500.0},
                        ipc=None,
                    )
                ])
            if request.events == ("cache-misses",):
                return iter([
                    PerfSample(
                        timestamp_sec=1.0,
                        values={"cache-misses": 200.0},
                        ipc=None,
                    )
                ])
            raise AssertionError(f"unexpected group attempt: {request.events}")

        with patch("perf_skill.perf._stream_perf_attempt", side_effect=fake_stream_attempt):
            samples = list(stream_perf_samples(request, target, group_mode="auto", pmu_slots=2))

        self.assertEqual(
            attempted_groups.count(
                (
                    (("instructions", "cycles"), ("cache-references", "cache-misses")),
                    ("instructions", "cycles", "cache-references", "cache-misses"),
                )
            ),
            1,
        )
        self.assertEqual(attempted_groups.count(((("instructions", "cycles"),), ("instructions", "cycles"))), 1)
        self.assertEqual(
            attempted_groups.count(
                ((("cache-references", "cache-misses"),), ("cache-references", "cache-misses"))
            ),
            1,
        )
        self.assertEqual(attempted_groups.count(((("cache-references",),), ("cache-references",))), 1)
        self.assertEqual(attempted_groups.count(((("cache-misses",),), ("cache-misses",))), 1)
        self.assertEqual(len(samples), 1)
        self.assertEqual(
            samples[0].values,
            {
                "instructions": 1000.0,
                "cycles": 2000.0,
                "cache-references": 500.0,
                "cache-misses": 200.0,
            },
        )
        self.assertEqual(samples[0].ipc, 0.5)


if __name__ == "__main__":
    unittest.main()
