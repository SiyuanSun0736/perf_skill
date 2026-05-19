from __future__ import annotations

import unittest
from unittest.mock import patch

from perf_skill.models import ObservationRequest, PerfSample, PerfStatError, TargetProcess
from perf_skill.perf import build_perf_command, build_retry_plans, format_retry_plan, parse_perf_csv_line, parse_perf_status_line, plan_event_groups, stream_perf_samples


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

    def test_build_retry_plans(self) -> None:
        plans = build_retry_plans(group_mode="auto", pmu_slots=4, retry_grouping=True)

        self.assertEqual(
            [(plan.group_mode, plan.pmu_slots) for plan in plans],
            [("auto", 4), ("auto", 2), ("auto", 1), ("off", 1)],
        )
        self.assertEqual(format_retry_plan(plans), "auto/4 -> auto/2 -> auto/1 -> off/1")

    def test_stream_perf_samples_retries_with_smaller_groups(self) -> None:
        request = ObservationRequest(
            statement="trace python 4242 inst cycles cache-misses",
            pid=4242,
            comm="python",
            events=("instructions", "cycles", "cache-references", "cache-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        sample = PerfSample(
            timestamp_sec=1.0,
            values={
                "instructions": 1000.0,
                "cycles": 2000.0,
                "cache-references": 500.0,
                "cache-misses": 200.0,
            },
            ipc=0.5,
        )
        attempts: list[tuple[str, int | None]] = []

        def fake_stream_attempt(request, target, *, group_mode, pmu_slots):
            attempts.append((group_mode, pmu_slots))
            if len(attempts) == 1:
                raise PerfStatError(
                    "uncounted grouped events",
                    kind="unsupported_events",
                    diagnostics=("<not counted>",),
                    unsupported_events={"instructions": "not counted"},
                )
            return iter([sample])

        with patch("perf_skill.perf._stream_perf_attempt", side_effect=fake_stream_attempt):
            samples = list(stream_perf_samples(request, target, group_mode="auto", pmu_slots=4))

        self.assertEqual(attempts, [("auto", 4), ("auto", 2)])
        self.assertEqual(samples, [sample])


if __name__ == "__main__":
    unittest.main()
