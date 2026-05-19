#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate release changelog markdown from git history between tags.",
    )
    parser.add_argument("--tag", required=True, help="current tag, such as v0.5.0")
    parser.add_argument("--previous-tag", help="optional explicit previous tag")
    parser.add_argument("--output", help="optional file path to write the changelog to")
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    sys.path.insert(0, str(repo_root / "src"))

    from perf_skill import __version__
    from perf_skill.release_tools import (
        collect_release_commits,
        find_previous_tag,
        git_revision_range,
        list_tags,
        read_repository_url,
        render_release_notes,
        validate_tag_matches_version,
    )

    version = validate_tag_matches_version(args.tag, __version__)
    previous_tag = args.previous_tag
    if previous_tag is None:
        previous_tag = find_previous_tag(list_tags(repo_root), args.tag)
    revision_range = git_revision_range(args.tag, previous_tag)
    commits = collect_release_commits(repo_root, revision_range)
    notes = render_release_notes(
        tag_name=args.tag,
        version=version,
        commits=commits,
        previous_tag=previous_tag,
        repository_url=read_repository_url(repo_root),
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(notes, encoding="utf-8")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
