#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run-observe.sh \"trace pid=1234 inst cycles\" [--plain] [--samples N] [--dry-run]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

find_repo_root() {
  if [[ -n "${PERF_SKILL_REPO:-}" && -d "${PERF_SKILL_REPO}/src/perf_skill" ]]; then
    printf '%s\n' "$PERF_SKILL_REPO"
    return 0
  fi

  if [[ -d "$PWD/src/perf_skill" ]]; then
    printf '%s\n' "$PWD"
    return 0
  fi

  local candidate="$script_dir"
  while [[ "$candidate" != "/" ]]; do
    if [[ -d "$candidate/src/perf_skill" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    candidate="$(dirname -- "$candidate")"
  done

  return 1
}

if repo_root="$(find_repo_root)"; then
  cd "$repo_root"
  export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
fi

exec python3 -m perf_skill observe "$@"