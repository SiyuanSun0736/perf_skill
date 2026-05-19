#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VERSION_PATTERN = re.compile(r"^(?:v)?(?P<version>\d+\.\d+\.\d+)$")
PACKAGE_VERSION_PATTERN = re.compile(r'^__version__ = "(?P<version>\d+\.\d+\.\d+)"$', re.MULTILINE)
VERSION_TARGETS = (
    Path("src/perf_skill/__init__.py"),
    Path("README.md"),
    Path("README-CN.md"),
    Path("docs/local-testing.md"),
)


@dataclass(frozen=True)
class FileUpdate:
    path: Path
    replacements: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_version_input(version_text: str) -> str:
    match = VERSION_PATTERN.fullmatch(version_text.strip())
    if match is None:
        raise ValueError("version must look like X.Y.Z or vX.Y.Z")
    return match.group("version")


def read_package_version(repo_root: Path) -> str:
    init_path = repo_root / VERSION_TARGETS[0]
    text = init_path.read_text(encoding="utf-8")
    match = PACKAGE_VERSION_PATTERN.search(text)
    if match is None:
        raise ValueError(f"could not find __version__ in {init_path}")
    return match.group("version")


def bump_version(
    repo_root: Path,
    version_text: str,
    *,
    dry_run: bool = False,
) -> tuple[str, str, tuple[FileUpdate, ...]]:
    new_version = normalize_version_input(version_text)
    current_version = read_package_version(repo_root)
    if new_version == current_version:
        return current_version, new_version, ()

    planned_updates: list[tuple[Path, str, int]] = []
    for relative_path in VERSION_TARGETS:
        path = repo_root / relative_path
        if not path.exists():
            if relative_path == VERSION_TARGETS[0]:
                raise FileNotFoundError(f"missing required file: {path}")
            continue

        original_text = path.read_text(encoding="utf-8")
        if relative_path == VERSION_TARGETS[0]:
            updated_text, replacements = PACKAGE_VERSION_PATTERN.subn(
                f'__version__ = "{new_version}"',
                original_text,
                count=1,
            )
            if replacements != 1:
                raise ValueError(f"could not replace __version__ in {path}")
        else:
            replacements = original_text.count(current_version)
            updated_text = original_text.replace(current_version, new_version)

        if replacements == 0:
            continue
        planned_updates.append((path, updated_text, replacements))

    if not dry_run:
        for path, updated_text, _ in planned_updates:
            path.write_text(updated_text, encoding="utf-8")

    return current_version, new_version, tuple(
        FileUpdate(path.relative_to(repo_root), replacements)
        for path, _, replacements in planned_updates
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump perf-skill package version references across source and docs.",
    )
    parser.add_argument("version", help="new version such as 0.6.0 or v0.6.0")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show which files would change without writing them",
    )
    args = parser.parse_args(argv)

    try:
        current_version, new_version, updates = bump_version(
            _repo_root(),
            args.version,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if not updates:
        print(f"version already {current_version}; nothing to update")
        return 0

    action = "would update" if args.dry_run else "updated"
    print(f"{action} version {current_version} -> {new_version}")
    for update in updates:
        suffix = "replacement" if update.replacements == 1 else "replacements"
        print(f"- {update.path.as_posix()} ({update.replacements} {suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())