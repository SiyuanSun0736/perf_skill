from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from perf_skill.release_tools import (
    find_previous_tag,
    git_revision_range,
    normalize_version_tag,
    read_repository_url,
    render_release_notes,
    validate_tag_matches_version,
)


class ReleaseToolsTest(unittest.TestCase):
    def test_normalize_version_tag(self) -> None:
        self.assertEqual(normalize_version_tag("v0.5.0"), "0.5.0")
        self.assertEqual(normalize_version_tag("0.5.0"), "0.5.0")

    def test_validate_tag_matches_version(self) -> None:
        self.assertEqual(validate_tag_matches_version("v0.5.0", "0.5.0"), "0.5.0")
        with self.assertRaises(ValueError):
            validate_tag_matches_version("v0.5.1", "0.5.0")

    def test_find_previous_tag(self) -> None:
        tags = ("v0.5.0", "v0.4.0", "v0.3.0")
        self.assertEqual(find_previous_tag(tags, "v0.5.0"), "v0.4.0")
        self.assertIsNone(find_previous_tag(("v0.5.0",), "v0.5.0"))

    def test_git_revision_range(self) -> None:
        self.assertEqual(git_revision_range("v0.5.0", "v0.4.0"), "v0.4.0..v0.5.0")
        self.assertEqual(git_revision_range("v0.5.0", None), "v0.5.0")

    def test_read_repository_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "pyproject.toml").write_text(
                """
[project]
name = "perf-skill"

[project.urls]
Repository = "https://github.com/example/perf_skill"
""".strip(),
                encoding="utf-8",
            )

            self.assertEqual(
                read_repository_url(repo_root),
                "https://github.com/example/perf_skill",
            )

    def test_render_release_notes(self) -> None:
        notes = render_release_notes(
            tag_name="v0.5.0",
            version="0.5.0",
            commits=("abc1234 Add release tooling", "def5678 Improve grouping"),
            previous_tag="v0.4.0",
            repository_url="https://github.com/example/perf_skill",
            generated_on=dt.date(2026, 5, 19),
        )

        self.assertIn("# v0.5.0", notes)
        self.assertIn("Package version: 0.5.0", notes)
        self.assertIn("Compare: https://github.com/example/perf_skill/compare/v0.4.0...v0.5.0", notes)
        self.assertIn("- abc1234 Add release tooling", notes)


if __name__ == "__main__":
    unittest.main()