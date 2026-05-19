from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from perf_skill.export import CsvSampleWriter, render_svg_report
from perf_skill.models import ObservationRequest, PerfSample, TargetProcess


class ExportHelpersTest(unittest.TestCase):
    def test_csv_writer_writes_samples(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles",
            pid=4242,
            comm="python",
            events=("instructions", "cycles"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        sample = PerfSample(
            timestamp_sec=1716100000.0,
            values={"instructions": 1234.0, "cycles": 4321.0},
            ipc=0.285582041,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "samples.csv"
            writer = CsvSampleWriter(str(output_path), request, target)
            writer.write(sample)
            writer.close()

            contents = output_path.read_text(encoding="utf-8")

        self.assertIn("timestamp_sec,timestamp_iso,pid,comm,instructions,cycles,ipc", contents)
        self.assertIn("4242,python,1234.000000,4321.000000,0.285582", contents)

    def test_render_svg_report(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles",
            pid=4242,
            comm="python",
            events=("instructions", "cycles"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        samples = [
            PerfSample(
                timestamp_sec=1716100000.0,
                values={"instructions": 1000.0, "cycles": 2000.0},
                ipc=0.5,
            ),
            PerfSample(
                timestamp_sec=1716100001.0,
                values={"instructions": 1400.0, "cycles": 2200.0},
                ipc=0.6363636,
            ),
        ]

        svg = render_svg_report(request, target, samples)

        self.assertIn("<svg", svg)
        self.assertIn("perf-skill-renderer:matplotlib", svg)
        self.assertIn("perf-skill-legend:on", svg)
        self.assertIn("instructions", svg)
        self.assertIn("cycles", svg)
        self.assertIn("ipc", svg)
        self.assertIn("path", svg)

    def test_render_svg_report_without_legend(self) -> None:
        request = ObservationRequest(
            statement="trace pid=4242 inst cycles",
            pid=4242,
            comm="python",
            events=("instructions", "cycles"),
            interval_ms=1000,
            history_size=20,
        )
        target = TargetProcess(pid=4242, comm="python")
        samples = [
            PerfSample(
                timestamp_sec=1716100000.0,
                values={"instructions": 1000.0, "cycles": 2000.0},
                ipc=0.5,
            ),
            PerfSample(
                timestamp_sec=1716100001.0,
                values={"instructions": 1400.0, "cycles": 2200.0},
                ipc=0.6363636,
            ),
        ]

        svg = render_svg_report(request, target, samples, show_legend=False)

        self.assertIn("perf-skill-renderer:matplotlib", svg)
        self.assertIn("perf-skill-legend:off", svg)
        self.assertNotIn("perf-skill-legend:on", svg)