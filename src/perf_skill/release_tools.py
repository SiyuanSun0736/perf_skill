from __future__ import annotations

import datetime as dt
import subprocess
import tomllib
from pathlib import Path


SKILL_PACKAGE_REQUIREMENT_PATH = Path(
    ".github/skills/hardware-event-observe/package-requirement.txt"
)
TEST_RELEASE_PREFIX = "test-"


def is_test_release_tag(tag_name: str) -> bool:
    return tag_name.startswith(TEST_RELEASE_PREFIX)


def normalize_version_tag(tag_name: str) -> str:
    if is_test_release_tag(tag_name):
        tag_name = tag_name[len(TEST_RELEASE_PREFIX):]
    return tag_name[1:] if tag_name.startswith("v") else tag_name


def validate_tag_matches_version(tag_name: str, version: str) -> str:
    normalized_tag = normalize_version_tag(tag_name)
    if normalized_tag != version:
        raise ValueError(
            f"tag {tag_name} does not match package version {version}"
        )
    return normalized_tag


def read_skill_package_requirement(repo_root: Path) -> str | None:
    requirement_path = repo_root / SKILL_PACKAGE_REQUIREMENT_PATH
    if not requirement_path.exists():
        return None

    for line in requirement_path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#"):
            return candidate
    return None


def validate_skill_package_requirement(repo_root: Path, version: str) -> str:
    requirement = read_skill_package_requirement(repo_root)
    expected_requirement = f"perf-skill=={version}"
    requirement_path = repo_root / SKILL_PACKAGE_REQUIREMENT_PATH

    if requirement is None:
        raise ValueError(f"missing skill package requirement in {requirement_path}")

    if requirement != expected_requirement:
        raise ValueError(
            f"skill package requirement {requirement!r} does not match expected {expected_requirement!r}"
        )

    return requirement


def read_repository_url(repo_root: Path) -> str | None:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    urls = project.get("project", {}).get("urls", {})
    repository = urls.get("Repository")
    if not repository:
        return None
    return repository.rstrip("/")


def list_tags(repo_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "tag", "--sort=-creatordate"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def find_previous_tag(tags: tuple[str, ...], current_tag: str) -> str | None:
    for tag in tags:
        if tag != current_tag:
            if is_test_release_tag(tag):
                continue
            return tag
    return None


def git_revision_range(current_tag: str, previous_tag: str | None) -> str:
    if previous_tag is None:
        return current_tag
    return f"{previous_tag}..{current_tag}"


def collect_release_commits(repo_root: Path, revision_range: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "log", "--no-merges", "--pretty=format:%h %s", revision_range],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def render_release_notes(
    *,
    tag_name: str,
    version: str,
    commits: tuple[str, ...],
    previous_tag: str | None,
    repository_url: str | None,
    generated_on: dt.date | None = None,
) -> str:
    release_date = generated_on or dt.date.today()
    lines = [
        f"# {tag_name}",
        "",
        f"Package version: {version}",
        f"Generated on: {release_date.isoformat()}",
    ]

    if previous_tag is not None:
        lines.append(f"Range: {previous_tag}..{tag_name}")
        if repository_url is not None:
            lines.append(f"Compare: {repository_url}/compare/{previous_tag}...{tag_name}")
    else:
        lines.append("Range: initial tagged release")

    lines.extend(["", "## Changes"])
    if commits:
        lines.extend(f"- {commit}" for commit in commits)
    else:
        lines.append("- No user-visible changes recorded between these tags.")
    lines.append("")
    return "\n".join(lines)
