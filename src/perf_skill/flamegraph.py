from __future__ import annotations

import os
from pathlib import Path
import subprocess

from perf_skill.models import ObservationError

FLAMEGRAPH_REPO_URL = "https://github.com/brendangregg/FlameGraph.git"


def resolve_perf_skill_home() -> Path:
    openclaw_home = Path(os.environ.get("OPENCLAW_HOME", str(Path.home() / ".openclaw"))).expanduser()
    default_home = openclaw_home / "perf-skill"
    return Path(os.environ.get("PERF_SKILL_HOME", str(default_home))).expanduser()


def resolve_flamegraph_dir() -> Path:
    default_dir = resolve_perf_skill_home() / "FlameGraph"
    return Path(os.environ.get("PERF_SKILL_FLAMEGRAPH_DIR", str(default_dir))).expanduser()


def build_clone_flamegraph_command(destination: str | Path) -> list[str]:
    return ["git", "clone", "--depth", "1", FLAMEGRAPH_REPO_URL, str(destination)]


def build_stackcollapse_command(repo_dir: str | Path) -> list[str]:
    return ["perl", str(Path(repo_dir) / "stackcollapse-perf.pl")]


def build_flamegraph_command(
    repo_dir: str | Path,
    *,
    title: str | None = None,
) -> list[str]:
    command = ["perl", str(Path(repo_dir) / "flamegraph.pl")]
    if title:
        command.extend(["--title", title])
    return command


def ensure_flamegraph_repo(repo_dir: str | Path | None = None) -> Path:
    destination = Path(repo_dir) if repo_dir is not None else resolve_flamegraph_dir()
    destination = destination.expanduser()
    stackcollapse_path = destination / "stackcollapse-perf.pl"
    flamegraph_path = destination / "flamegraph.pl"

    if stackcollapse_path.is_file() and flamegraph_path.is_file():
        return destination

    if destination.exists() and any(destination.iterdir()):
        raise ObservationError(f"FlameGraph directory is incomplete: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            build_clone_flamegraph_command(destination),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise ObservationError("git not found in PATH; cannot bootstrap FlameGraph") from error

    if completed.returncode != 0:
        details = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        raise ObservationError(details or f"failed to clone FlameGraph into {destination}")

    if not stackcollapse_path.is_file() or not flamegraph_path.is_file():
        raise ObservationError(f"FlameGraph clone is missing required scripts: {destination}")
    return destination


def write_flamegraph(
    script_output: str,
    output_path: str,
    *,
    repo_dir: str | Path | None = None,
    title: str | None = None,
) -> None:
    resolved_repo_dir = ensure_flamegraph_repo(repo_dir)
    collapsed_output = _run_filter_command(
        build_stackcollapse_command(resolved_repo_dir),
        stdin=script_output,
        label="stackcollapse-perf.pl",
    )
    if not collapsed_output.strip():
        raise ObservationError(
            "perf script produced no stack samples; record with call graphs first or choose a different perf.data file"
        )

    svg_output = _run_filter_command(
        build_flamegraph_command(resolved_repo_dir, title=title),
        stdin=collapsed_output,
        label="flamegraph.pl",
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg_output, encoding="utf-8")


def _run_filter_command(command: list[str], *, stdin: str, label: str) -> str:
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        if command and command[0] == "perl":
            raise ObservationError("perl not found in PATH; FlameGraph requires perl") from error
        raise ObservationError(f"failed to start {label}") from error

    if completed.returncode != 0:
        details = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        raise ObservationError(details or f"{label} exited with status {completed.returncode}")
    return completed.stdout