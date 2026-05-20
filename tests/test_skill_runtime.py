from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SOURCE = REPO_ROOT / ".github/skills/hardware-event-observe/scripts/run-observe.sh"
PACKAGE_REQUIREMENT_SOURCE = REPO_ROOT / ".github/skills/hardware-event-observe/package-requirement.txt"


class SkillRuntimeLayoutTest(unittest.TestCase):
    def test_global_claw_skill_installs_use_matching_runtime_home(self) -> None:
        for home_name in (".openclaw", ".ironclaw", ".zeroclaw"):
            with self.subTest(home_name=home_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_root = Path(temp_dir)
                    skill_dir = temp_root / home_name / "skills" / "hardware-event-observe"
                    scripts_dir = skill_dir / "scripts"
                    scripts_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(SCRIPT_SOURCE, scripts_dir / "run-observe.sh")
                    shutil.copy2(PACKAGE_REQUIREMENT_SOURCE, skill_dir / "package-requirement.txt")

                    capture_dir = temp_root / "capture"
                    capture_dir.mkdir()
                    fake_bin_dir = temp_root / "fake-bin"
                    fake_bin_dir.mkdir()
                    fake_python = fake_bin_dir / "python3"
                    fake_python.write_text(
                        textwrap.dedent(
                            """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
  target="${3:?}"
  mkdir -p "$target/bin"
  cat > "$target/bin/python3" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "perf_skill" ]]; then
  printf '%s\n' "${PERF_SKILL_HOME:-}" > "__CAPTURE_DIR__/perf_skill_home.txt"
  exit 0
fi
exit 0
INNER
  chmod +x "$target/bin/python3"
  exit 0
fi
if [[ "${1:-}" == "--help" ]]; then
  exit 0
fi
exit 0
""".replace("__CAPTURE_DIR__", str(capture_dir))
                        ),
                        encoding="utf-8",
                    )
                    fake_python.chmod(0o755)

                    cwd = temp_root / "cwd"
                    cwd.mkdir()
                    env = {
                        "HOME": str(temp_root / "home"),
                        "PATH": f"{fake_bin_dir}:{os.environ['PATH']}",
                    }

                    completed = subprocess.run(
                        ["bash", str(scripts_dir / "run-observe.sh"), "trace pid=1 cycles", "--dry-run"],
                        cwd=cwd,
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    expected_home = temp_root / home_name / "perf-skill"
                    self.assertEqual(
                        (capture_dir / "perf_skill_home.txt").read_text(encoding="utf-8").strip(),
                        str(expected_home),
                    )
                    self.assertTrue((expected_home / "venv" / "bin" / "python3").exists())


if __name__ == "__main__":
    unittest.main()