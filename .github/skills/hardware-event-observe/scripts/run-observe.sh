#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run-observe.sh \"trace pid=1234 inst cycles\" [--plain] [--samples N] [--dry-run]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/../../../.." && pwd)"

cd "$repo_root"
PYTHONPATH=src python3 -m perf_skill observe "$@"