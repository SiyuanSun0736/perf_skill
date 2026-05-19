from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from perf_skill.flamegraph import write_flamegraph


class FlameGraphTest(unittest.TestCase):
    def test_write_flamegraph_bootstraps_repo_and_writes_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir) / "FlameGraph"
            output_path = Path(temp_dir) / "out" / "node-flamegraph.svg"

            def fake_run(command, **kwargs):
                if command[:3] == ["git", "clone", "--depth"]:
                    repo_dir.mkdir(parents=True, exist_ok=True)
                    (repo_dir / "stackcollapse-perf.pl").write_text("#!/usr/bin/env perl\n", encoding="utf-8")
                    (repo_dir / "flamegraph.pl").write_text("#!/usr/bin/env perl\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command == ["perl", str(repo_dir / "stackcollapse-perf.pl")]:
                    self.assertEqual(kwargs["input"], "perf script output")
                    return subprocess.CompletedProcess(command, 0, "main;foo 1\n", "")
                if command == [
                    "perl",
                    str(repo_dir / "flamegraph.pl"),
                    "--title",
                    "perf.data: node.data",
                ]:
                    self.assertEqual(kwargs["input"], "main;foo 1\n")
                    return subprocess.CompletedProcess(command, 0, "<svg>flame</svg>\n", "")
                raise AssertionError(f"unexpected command: {command}")

            with patch("perf_skill.flamegraph.subprocess.run", side_effect=fake_run):
                write_flamegraph(
                    "perf script output",
                    str(output_path),
                    repo_dir=repo_dir,
                    title="perf.data: node.data",
                )

            self.assertEqual(output_path.read_text(encoding="utf-8"), "<svg>flame</svg>\n")


if __name__ == "__main__":
    unittest.main()