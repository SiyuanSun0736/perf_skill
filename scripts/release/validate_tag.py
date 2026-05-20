#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate that a git tag and bundled skill runtime requirement match perf_skill.__version__.",
    )
    parser.add_argument("tag", help="tag to validate, such as v0.5.0 or test-v0.5.0")
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    sys.path.insert(0, str(repo_root / "src"))

    from perf_skill import __version__
    from perf_skill.release_tools import (
        validate_skill_layout_sync,
        validate_skill_package_requirement,
        validate_tag_matches_version,
    )

    normalized_version = validate_tag_matches_version(args.tag, __version__)
    synced_files = validate_skill_layout_sync(repo_root)
    requirement = validate_skill_package_requirement(repo_root, normalized_version)
    print(f"validated tag {args.tag} against package version {normalized_version}")
    print(f"validated mirrored skill layout across {len(synced_files)} files")
    print(f"validated skill runtime package requirement {requirement}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
