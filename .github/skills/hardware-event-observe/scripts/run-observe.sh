#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run-observe.sh \"trace pid=1234 inst cycles for 5 seconds\" [--plain] [--samples N] [--seconds N] [--dry-run]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
openclaw_home="${OPENCLAW_HOME:-$HOME/.openclaw}"
perf_skill_home="${PERF_SKILL_HOME:-$openclaw_home/perf-skill}"
venv_dir="${PERF_SKILL_VENV_DIR:-$perf_skill_home/venv}"
venv_python="$venv_dir/bin/python3"
install_stamp="$perf_skill_home/.install-stamp"

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

ensure_python3() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi

  echo "error: python3 is required to run perf-skill" >&2
  exit 2
}

ensure_runtime_env() {
  local repo_root="$1"

  mkdir -p "$perf_skill_home"

  if ! needs_runtime_install "$repo_root"; then
    return 0
  fi

  echo "bootstrapping perf-skill runtime in $venv_dir" >&2
  if [[ ! -x "$venv_python" ]]; then
    rm -rf "$venv_dir"
    if ! python3 -m venv "$venv_dir"; then
      echo "error: failed to create virtual environment with python3 -m venv" >&2
      echo "hint: install the system python venv package, for example python3-venv" >&2
      exit 2
    fi
  fi

  if ! "$venv_python" -m pip install --quiet --disable-pip-version-check --editable "$repo_root"; then
    echo "error: failed to install perf-skill into $venv_dir" >&2
    exit 2
  fi

  date -u +%FT%TZ > "$install_stamp"
}

needs_runtime_install() {
  local repo_root="$1"

  if [[ ! -x "$venv_python" ]]; then
    return 0
  fi

  if [[ ! -f "$install_stamp" ]]; then
    return 0
  fi

  if [[ "$repo_root/pyproject.toml" -nt "$install_stamp" ]]; then
    return 0
  fi

  if ! "$venv_python" - <<'PY' >/dev/null 2>&1
import matplotlib
import perf_skill
PY
  then
    return 0
  fi

  return 1
}

ensure_python3

if ! repo_root="$(find_repo_root)"; then
  echo "error: could not locate the perf-skill repository root" >&2
  echo "hint: run from the repository root or set PERF_SKILL_REPO=/path/to/perf_skill" >&2
  exit 2
fi

cd "$repo_root"
ensure_runtime_env "$repo_root"

subcommand="observe"
if [[ $# -ge 1 ]]; then
  case "$1" in
    observe|events|exercise)
      subcommand="$1"
      shift
      ;;
  esac
fi

exec "$venv_python" -m perf_skill "$subcommand" "$@"