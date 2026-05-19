from __future__ import annotations

import unittest

from perf_skill.models import ObservationRequest, TargetProcess
from perf_skill.perf import build_perf_command, parse_perf_csv_line, parse_perf_status_line, plan_event_groups


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


if __name__ == "__main__":
    unittest.main()
