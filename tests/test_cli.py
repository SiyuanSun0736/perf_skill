from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
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

    def test_events_subcommand_can_list_perf_events(self) -> None:
        stdout = io.StringIO()
        completed = subprocess.CompletedProcess(
            args=["perf", "list", "cache"],
            returncode=0,
            stdout="cache-misses\ncache-references\n",
            stderr="",
        )
        with patch("perf_skill.cli.subprocess.run", return_value=completed) as run_mock, redirect_stdout(stdout):
            exit_code = main(["events", "cache"])

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

    def test_observe_summary_prints_python_analysis(self) -> None:
        stdout = io.StringIO()
        renderer = Mock()

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 2000.0}, ipc=0.5)
            yield PerfSample(timestamp_sec=2.0, values={"instructions": 1400.0, "cycles": 2200.0}, ipc=0.6363636)

        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()),
            patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            redirect_stdout(stdout),
        ):
            exit_code = main(["observe", "trace pid=4242 inst cycles", "--plain", "--summary"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("summary   : 2 samples over 1.00s for pid=4242 comm=node", output)
        self.assertIn("metric    : instructions avg=1.20K peak=1.40K last=1.40K trend=rising", output)

    def test_observe_summary_marks_anomaly_points(self) -> None:
        stdout = io.StringIO()
        renderer = Mock()

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0}, ipc=1.0)
            yield PerfSample(timestamp_sec=2.0, values={"instructions": 980.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0}, ipc=0.98)
            yield PerfSample(timestamp_sec=3.0, values={"instructions": 400.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 18.0}, ipc=0.4)

        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()),
            patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "trace pid=4242 inst cycles branches branch-misses",
                "--plain",
                "--summary",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("anomaly   : at=3.00s ipc drop baseline=0.990 current=0.400 delta=-59.6%", output)
        self.assertIn("anomaly   : at=3.00s branch-miss-rate surge baseline=2.00% current=18.00% delta=+800.0%", output)

    def test_observe_summary_out_writes_json(self) -> None:
        renderer = Mock()

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 2000.0}, ipc=0.5)

        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "summary.json"
            with (
                patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
                patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
                patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()),
                patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            ):
                exit_code = main([
                    "observe",
                    "trace pid=4242 inst cycles",
                    "--plain",
                    "--summary-out",
                    str(summary_path),
                ])

            self.assertEqual(exit_code, 0)
            payload = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["pid"], 4242)
        self.assertEqual(payload["comm"], "node")
        self.assertEqual(payload["sample_count"], 1)

    def test_observe_dry_run_perf_data_request_generates_named_output(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli._current_data_timestamp", return_value="20260519T120000"),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "追踪 node 的 cycles 并输出 perf.data",
                "--dry-run",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("data-out  : out/node_targetpid4242_cycles_data_20260519T120000.data", output)
        self.assertIn("command   : perf record", output)

    def test_observe_perf_data_request_runs_perf_record(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli._current_data_timestamp", return_value="20260519T120000"),
            patch("perf_skill.cli._run_command", return_value="recorded") as run_command_mock,
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "追踪 node 的 cycles 并输出 perf.data",
                "--seconds",
                "5",
            ])

        self.assertEqual(exit_code, 0)
        run_command_mock.assert_called_once_with(
            [
                "perf",
                "record",
                "-o",
                "out/node_targetpid4242_cycles_data_20260519T120000.data",
                "-e",
                "{instructions,cycles}",
                "-p",
                "4242",
                "--",
                "sleep",
                "5",
            ]
        )
        output = stdout.getvalue()
        self.assertIn("recorded", output)
        self.assertIn("data-out  : out/node_targetpid4242_cycles_data_20260519T120000.data", output)

    def test_observe_dry_run_flamegraph_request_forces_perf_record_with_call_graphs(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli._current_data_timestamp", return_value="20260519T120000"),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "追踪 node 的 cycles 并生成火焰图",
                "--dry-run",
                "--seconds",
                "5",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("data-out  : out/node_targetpid4242_cycles_data_20260519T120000.data", output)
        self.assertIn(
            "flamegraph: out/node_targetpid4242_cycles_data_20260519T120000-flamegraph.svg",
            output,
        )
        self.assertIn("command   : perf record -g", output)

    def test_observe_perf_data_request_with_flamegraph_renders_svg(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="node")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli._current_data_timestamp", return_value="20260519T120000"),
            patch("perf_skill.cli._run_command", side_effect=["recorded", "script output"]) as run_command_mock,
            patch("perf_skill.cli.write_flamegraph") as write_flamegraph_mock,
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "observe",
                "追踪 node 的 cycles 并生成火焰图",
                "--seconds",
                "5",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            run_command_mock.call_args_list,
            [
                unittest.mock.call([
                    "perf",
                    "record",
                    "-g",
                    "-o",
                    "out/node_targetpid4242_cycles_data_20260519T120000.data",
                    "-e",
                    "{instructions,cycles}",
                    "-p",
                    "4242",
                    "--",
                    "sleep",
                    "5",
                ]),
                unittest.mock.call([
                    "perf",
                    "script",
                    "-i",
                    "out/node_targetpid4242_cycles_data_20260519T120000.data",
                ]),
            ],
        )
        write_flamegraph_mock.assert_called_once_with(
            "script output",
            "out/node_targetpid4242_cycles_data_20260519T120000-flamegraph.svg",
            title="perf.data: node_targetpid4242_cycles_data_20260519T120000.data",
        )
        self.assertIn(
            "flamegraph: out/node_targetpid4242_cycles_data_20260519T120000-flamegraph.svg",
            stdout.getvalue(),
        )

    def test_observe_parse_data_request_runs_perf_script(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "node_targetpid4242_cycles_data_20260519T120000.data"
            data_path.write_text("", encoding="utf-8")

            with (
                patch("perf_skill.cli._run_command", return_value="parsed events") as run_command_mock,
                redirect_stdout(stdout),
            ):
                exit_code = main([
                    "observe",
                    f"解析 {data_path}",
                ])

        self.assertEqual(exit_code, 0)
        run_command_mock.assert_called_once_with([
            "perf",
            "script",
            "-i",
            str(data_path),
        ])
        self.assertIn("parsed events", stdout.getvalue())

    def test_observe_parse_data_summary_uses_python_report(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "node_targetpid4242_cycles_data_20260519T120000.data"
            data_path.write_text("", encoding="utf-8")
            script_output = "\n".join(
                [
                    "node 4242/4242 [002] 123.456: cycles:",
                    "        7f00abcd v8::Function+0x10 (node)",
                    "        7f00aaaa main (node)",
                    "node 4242/4242 [002] 123.556: cycles:",
                    "        7f00abce v8::Function+0x10 (node)",
                    "        7f00aaaa main (node)",
                    "node 4242/4243 [002] 123.656: sched:sched_switch:",
                    "        ffffffff8107b6d7 finish_task_switch+0x147 ([kernel.kallsyms])",
                    "        ffffffff8106ffff __schedule+0x3ff ([kernel.kallsyms])",
                ]
            )

            with (
                patch("perf_skill.cli._run_command", return_value=script_output) as run_command_mock,
                redirect_stdout(stdout),
            ):
                exit_code = main([
                    "observe",
                    f"解析 {data_path}",
                    "--summary",
                ])

        self.assertEqual(exit_code, 0)
        run_command_mock.assert_called_once_with([
            "perf",
            "script",
            "-i",
            str(data_path),
        ])
        output = stdout.getvalue()
        self.assertIn(f"data      : {data_path}", output)
        self.assertIn("top-event : cycles=2", output)
        self.assertIn("top-thread: node pid=4242 tid=4242=2", output)
        self.assertIn("top-callchain[cycles]: v8::Function+0x10 [node] <- main [node]=2", output)
        self.assertIn("top-callchain[sched:sched_switch]: finish_task_switch+0x147 [[kernel.kallsyms]] <- __schedule+0x3ff [[kernel.kallsyms]]=1", output)
        self.assertIn("top-callchain: v8::Function+0x10 [node] <- main [node]=2", output)

    def test_observe_parse_data_report_stdio_runs_perf_report(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "node.data"
            data_path.write_text("", encoding="utf-8")

            with (
                patch("perf_skill.cli._run_command", return_value="report body") as run_command_mock,
                redirect_stdout(stdout),
            ):
                exit_code = main([
                    "observe",
                    "--data-in",
                    str(data_path),
                    "--report-stdio",
                ])

        self.assertEqual(exit_code, 0)
        run_command_mock.assert_called_once_with([
            "perf",
            "report",
            "--stdio",
            "-i",
            str(data_path),
        ])
        output = stdout.getvalue()
        self.assertIn("report    : perf report --stdio", output)
        self.assertIn("report body", output)

    def test_observe_parse_data_annotate_top_uses_hottest_symbol(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "node.data"
            data_path.write_text("", encoding="utf-8")
            script_output = "\n".join(
                [
                    "node 4242/4242 [002] 123.456: cycles:",
                    "        7f00abcd v8::Function+0x10 (node)",
                    "        7f00aaaa main (node)",
                    "node 4242/4242 [002] 123.556: cycles:",
                    "        7f00abce v8::Function+0x10 (node)",
                    "        7f00aaaa main (node)",
                ]
            )

            with (
                patch("perf_skill.cli._run_command", side_effect=[script_output, "annotate body"]) as run_command_mock,
                redirect_stdout(stdout),
            ):
                exit_code = main([
                    "observe",
                    "--data-in",
                    str(data_path),
                    "--annotate-top",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            run_command_mock.call_args_list,
            [
                unittest.mock.call(["perf", "script", "-i", str(data_path)]),
                unittest.mock.call([
                    "perf",
                    "annotate",
                    "--stdio",
                    "-i",
                    str(data_path),
                    "--symbol",
                    "v8::Function+0x10",
                ]),
            ],
        )
        output = stdout.getvalue()
        self.assertIn("annotate  : v8::Function+0x10", output)
        self.assertIn("annotate body", output)

    def test_observe_parse_data_request_can_render_flamegraph(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "node.data"
            data_path.write_text("", encoding="utf-8")

            with (
                patch("perf_skill.cli._run_command", return_value="script output") as run_command_mock,
                patch("perf_skill.cli.write_flamegraph") as write_flamegraph_mock,
                redirect_stdout(stdout),
            ):
                exit_code = main([
                    "observe",
                    "--data-in",
                    str(data_path),
                    "--flamegraph-out",
                    "out/node-flamegraph.svg",
                ])

        self.assertEqual(exit_code, 0)
        run_command_mock.assert_called_once_with([
            "perf",
            "script",
            "-i",
            str(data_path),
        ])
        write_flamegraph_mock.assert_called_once_with(
            "script output",
            "out/node-flamegraph.svg",
            title="perf.data: node.data",
        )
        output = stdout.getvalue()
        self.assertIn("flamegraph: out/node-flamegraph.svg", output)
        self.assertNotIn("script output", output)

    def test_exercise_dry_run_defaults_to_observing_spawned_load_process(self) -> None:
        stdout = io.StringIO()
        with (
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "exercise",
                "stress-ng",
                "--load-args",
                "--cpu 2 --timeout 5",
                "--dry-run",
            ])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("load-tool : stress-ng", output)
        self.assertIn("load-cmd  : stress-ng --cpu 2 --timeout 5", output)
        self.assertIn("target    : spawned load process comm=stress-ng pid=<load-pid>", output)
        self.assertIn("command   : perf stat", output)

    def test_exercise_runs_load_tool_and_prints_summary(self) -> None:
        stdout = io.StringIO()
        renderer = Mock()
        load_process = Mock()
        load_process.pid = 6001
        load_process.poll.side_effect = [None, None, 0]
        load_process.communicate.return_value = ("stress summary", "")
        load_process.returncode = 0

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 2000.0}, ipc=0.5)
            yield PerfSample(timestamp_sec=2.0, values={"instructions": 1400.0, "cycles": 2200.0}, ipc=0.6363636)

        with (
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli.subprocess.Popen", return_value=load_process) as popen_mock,
            patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()) as stream_mock,
            patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "exercise",
                "stress-ng",
                "--load-args",
                "--cpu 1 --timeout 1",
                "--plain",
                "--summary",
            ])

        self.assertEqual(exit_code, 0)
        popen_mock.assert_called_once_with(
            ["stress-ng", "--cpu", "1", "--timeout", "1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        request, target = stream_mock.call_args.args[:2]
        self.assertEqual(request.pid, 6001)
        self.assertEqual(target.pid, 6001)
        output = stdout.getvalue()
        self.assertIn("summary   : 2 samples over 1.00s for pid=6001 comm=stress-ng", output)
        self.assertIn("load-tool : stress-ng", output)
        self.assertIn("load-exit : 0", output)
        self.assertIn("stress summary", output)

    def test_exercise_can_observe_explicit_target_while_running_ab(self) -> None:
        stdout = io.StringIO()
        renderer = Mock()
        load_process = Mock()
        load_process.pid = 7001
        load_process.poll.side_effect = [None, 0]
        load_process.communicate.return_value = ("ab summary", "")
        load_process.returncode = 0

        def fake_stream(*args, **kwargs):
            yield PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 2000.0}, ipc=0.5)

        with (
            patch("perf_skill.cli.resolve_target", return_value=TargetProcess(pid=4242, comm="nginx")),
            patch("perf_skill.cli.detect_pmu_slot_limit", return_value=4),
            patch("perf_skill.cli.subprocess.Popen", return_value=load_process),
            patch("perf_skill.cli.stream_perf_samples", return_value=fake_stream()) as stream_mock,
            patch("perf_skill.cli.DashboardRenderer", return_value=renderer),
            redirect_stdout(stdout),
        ):
            exit_code = main([
                "exercise",
                "ab",
                "trace comm=nginx cache-misses",
                "--load-args",
                "-n 100 -c 10 http://127.0.0.1/",
                "--plain",
            ])

        self.assertEqual(exit_code, 0)
        request, target = stream_mock.call_args.args[:2]
        self.assertEqual(request.comm, "nginx")
        self.assertEqual(target.pid, 4242)
        output = stdout.getvalue()
        self.assertIn("load-tool : ab", output)
        self.assertIn("ab summary", output)


if __name__ == "__main__":
    unittest.main()