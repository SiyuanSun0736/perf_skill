from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from perf_skill.models import ObservationRequest, PerfSample, TargetProcess
from perf_skill.ui import DashboardRenderer


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class DashboardRendererTest(unittest.TestCase):
    def test_plain_output_marks_live_anomalies(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles branches branch-misses",
            pid=4242,
            comm="node",
            events=("instructions", "cycles", "branches", "branch-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="node")
        renderer = DashboardRenderer(request, target, plain_output=True)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            renderer.render(PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0}, ipc=1.0))
            renderer.render(PerfSample(timestamp_sec=2.0, values={"instructions": 980.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0}, ipc=0.98))
            renderer.render(PerfSample(timestamp_sec=3.0, values={"instructions": 400.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 18.0}, ipc=0.4))

        output = stdout.getvalue()
        self.assertIn(
            "alerts=ipc drop 0.990->0.400 (-59.6%); branch-miss-rate surge 2.00%->18.00% (+800.0%)",
            output,
        )

    def test_dashboard_output_lists_recent_alerts(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles branches branch-misses",
            pid=4242,
            comm="node",
            events=("instructions", "cycles", "branches", "branch-misses"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="node")
        renderer = DashboardRenderer(request, target, plain_output=False)

        stdout = _TtyBuffer()
        with redirect_stdout(stdout):
            renderer.render(PerfSample(timestamp_sec=1.0, values={"instructions": 1000.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0}, ipc=1.0))
            renderer.render(PerfSample(timestamp_sec=2.0, values={"instructions": 980.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 2.0}, ipc=0.98))
            renderer.render(PerfSample(timestamp_sec=3.0, values={"instructions": 400.0, "cycles": 1000.0, "branches": 100.0, "branch-misses": 18.0}, ipc=0.4))

        output = stdout.getvalue()
        self.assertIn("alerts", output)
        self.assertIn("summary          total=2 recent30s=2 last=", output)
        self.assertIn("ipc drop 0.990->0.400 (-59.6%)", output)
        self.assertIn("branch-miss-rate surge 2.00%->18.00% (+800.0%)", output)


if __name__ == "__main__":
    unittest.main()
