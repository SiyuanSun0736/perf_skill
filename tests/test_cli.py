from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from perf_skill.cli import main
from perf_skill.models import PerfSample, TargetProcess


class CliTest(unittest.TestCase):
    def test_observe_dry_run_is_reported_as_simulated_preview(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="python")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "trace pid=4242 inst cycles for 5 seconds 10 samples dry-run",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn(
            "preview   : simulated dry-run only; perf itself has no --dry-run option",
            output,
        )
        self.assertIn("samples   : 10", output)
        self.assertIn("seconds   : 5", output)
        self.assertIn("command   : perf stat", output)

    def test_observe_statement_can_list_perf_events(self) -> None:
        stdout = io.StringIO()
        completed = subprocess.CompletedProcess(
            args=["perf", "list", "cache"],
            returncode=0,
            stdout="cache-misses\ncache-references\n",
            stderr="",
        )
        with patch("perf_skill.cli.subprocess.run", return_value=completed) as run_mock, redirect_stdout(stdout):
            exit_code = main(["observe", "查看 cache 相关事件"])

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once_with(
            ["perf", "list", "cache"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertIn("cache-misses", stdout.getvalue())

    def test_observe_statement_seconds_limit_stops_collection(self) -> None:
        stdout = io.StringIO()
        renderer = Mock()

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1.0, "cycles": 2.0}, ipc=0.5)
            yield PerfSample(timestamp_sec=2.0, values={"instructions": 2.0, "cycles": 4.0}, ipc=0.5)
            yield PerfSample(timestamp_sec=3.0, values={"instructions": 3.0, "cycles": 6.0}, ipc=0.5)

        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="python")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()),
            patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            patch("perf_skill.cli.time.monotonic", side_effect=[0.0, 0.4, 1.2]),
            redirect_stdout(stdout),
        ):
            exit_code = main(["observe", "trace pid=4242 inst cycles for 1 seconds", "--plain"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(renderer.render.call_count, 2)

    def test_observe_dry_run_generates_default_svg_path_from_statement(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "生成10s内node的branchs的图像",
                "--dry-run",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("seconds   : 10", output)
        self.assertIn("svg-out   : out/node-branches.svg", output)

    def test_observe_statement_svg_request_writes_default_svg_report(self) -> None:
        stdout = io.StringIO()
        renderer = Mock()

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1.0, "cycles": 2.0}, ipc=0.5)

        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()),
            patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            patch("perf_skill.cli.write_svg_report") as write_svg_report_mock,
            redirect_stdout(stdout),
        ):
            exit_code = main(["observe", "探测20秒node的cycles并生成图像", "--plain"])

        self.assertEqual(exit_code, 0)
        write_svg_report_mock.assert_called_once()
        self.assertEqual(write_svg_report_mock.call_args.args[0], "out/node-cycles.svg")


if __name__ == "__main__":
    unittest.main()