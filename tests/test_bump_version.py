from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_bump_version_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts/release/bump_version.py"
    spec = importlib.util.spec_from_file_location("bump_version_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_file(repo_root: Path, relative_path: str, content: str) -> None:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class BumpVersionScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_bump_version_module()

    def _seed_repo(self, repo_root: Path) -> None:
        _write_file(
            repo_root,
            "src/perf_skill/__init__.py",
            '"""perf-skill package."""\n\n__all__ = ["__version__"]\n\n__version__ = "0.5.0"\n',
        )
        _write_file(
            repo_root,
            ".github/skills/hardware-event-observe/package-requirement.txt",
            "perf-skill==0.5.0\n",
        )
        _write_file(
            repo_root,
            "README.md",
            "Pushing a tag such as `v0.5.0`\n"
            "PYTHONPATH=src python3 scripts/release/validate_tag.py v0.5.0\n",
        )
        _write_file(
            repo_root,
            "README-CN.md",
            "推送类似 `v0.5.0` 这样的 tag 时\n"
            "PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v0.5.0\n",
        )
        _write_file(
            repo_root,
            "docs/local-testing.md",
            "PYTHONPATH=src python3 scripts/release/validate_tag.py v0.5.0\n"
            "git tag -f v0.5.0 >/dev/null 2>&1\n"
            "- `perf_skill-0.5.0.tar.gz`\n"
            "- `perf_skill-0.5.0-py3-none-any.whl`\n",
        )

    def test_bump_version_updates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._seed_repo(repo_root)

            current_version, new_version, updates = self.module.bump_version(repo_root, "v0.6.1")

            self.assertEqual(current_version, "0.5.0")
            self.assertEqual(new_version, "0.6.1")
            self.assertEqual(
                {update.path.as_posix() for update in updates},
                {
                    "src/perf_skill/__init__.py",
                    ".github/skills/hardware-event-observe/package-requirement.txt",
                    "README.md",
                    "README-CN.md",
                    "docs/local-testing.md",
                },
            )
            self.assertIn('__version__ = "0.6.1"', (repo_root / "src/perf_skill/__init__.py").read_text(encoding="utf-8"))
            self.assertEqual(
                (repo_root / ".github/skills/hardware-event-observe/package-requirement.txt").read_text(encoding="utf-8"),
                "perf-skill==0.6.1\n",
            )
            self.assertNotIn("0.5.0", (repo_root / "README.md").read_text(encoding="utf-8"))
            self.assertNotIn("0.5.0", (repo_root / "README-CN.md").read_text(encoding="utf-8"))
            local_testing = (repo_root / "docs/local-testing.md").read_text(encoding="utf-8")
            self.assertIn("perf_skill-0.6.1.tar.gz", local_testing)
            self.assertIn("perf_skill-0.6.1-py3-none-any.whl", local_testing)

    def test_bump_version_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._seed_repo(repo_root)
            original_text = (repo_root / "README.md").read_text(encoding="utf-8")

            current_version, new_version, updates = self.module.bump_version(
                repo_root,
                "0.6.1",
                dry_run=True,
            )

            self.assertEqual(current_version, "0.5.0")
            self.assertEqual(new_version, "0.6.1")
            self.assertTrue(updates)
            self.assertEqual((repo_root / "README.md").read_text(encoding="utf-8"), original_text)

    def test_bump_version_rejects_invalid_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            self._seed_repo(repo_root)

            with self.assertRaises(ValueError):
                self.module.bump_version(repo_root, "0.6")


if __name__ == "__main__":
    unittest.main()