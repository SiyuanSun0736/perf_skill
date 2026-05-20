#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run-observe.sh \"trace pid=1234 inst cycles for 5 seconds\" [--plain] [--samples N] [--seconds N] [--dry-run]" >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
script_path="$script_dir/$(basename -- "${BASH_SOURCE[0]}")"
skill_dir="$(dirname -- "$script_dir")"
skills_dir="$(dirname -- "$skill_dir")"
package_requirement_file="$skill_dir/package-requirement.txt"
workspace_root=""
detected_openclaw_home=""

detect_install_layout() {
  if [[ "$(basename -- "$skills_dir")" != "skills" ]]; then
    return 0
  fi

  local parent_dir
  parent_dir="$(dirname -- "$skills_dir")"
  case "$(basename -- "$parent_dir")" in
    .github)
      return 0
      ;;
    .openclaw)
      detected_openclaw_home="$parent_dir"
      ;;
    *)
      workspace_root="$parent_dir"
      ;;
  esac
}

find_local_repo_root() {
  if [[ -n "${PERF_SKILL_REPO:-}" ]]; then
    if [[ -d "${PERF_SKILL_REPO}/src/perf_skill" ]]; then
      printf '%s\n' "$PERF_SKILL_REPO"
      return 0
    fi

    echo "error: PERF_SKILL_REPO must point to a perf-skill repository root" >&2
    exit 2
  fi

  if [[ -n "$workspace_root" && -d "$workspace_root/src/perf_skill" ]]; then
    printf '%s\n' "$workspace_root"
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

resolve_run_cwd() {
  if [[ -n "${PERF_SKILL_CWD:-}" ]]; then
    printf '%s\n' "$PERF_SKILL_CWD"
    return 0
  fi

  if [[ -n "$workspace_root" ]]; then
    printf '%s\n' "$workspace_root"
    return 0
  fi

  if [[ -n "${1:-}" ]]; then
    printf '%s\n' "$1"
    return 0
  fi

  printf '%s\n' "$PWD"
}

read_default_package_source() {
  local line=""

  if [[ -f "$package_requirement_file" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
      if [[ -n "$line" && "${line:0:1}" != "#" ]]; then
        printf '%s\n' "$line"
        return 0
      fi
    done < "$package_requirement_file"
  fi

  printf '%s\n' "perf-skill"
}

ensure_python3() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi

  echo "error: python3 is required to run perf-skill" >&2
  exit 2
}

ensure_package_source_prereqs() {
  local install_source="$1"

  case "$install_source" in
    git+*)
      if command -v git >/dev/null 2>&1; then
        return 0
      fi

      echo "error: git is required when PERF_SKILL_PACKAGE_SOURCE uses a git URL" >&2
      exit 2
      ;;
  esac
}

ensure_runtime_env() {
  local install_source="$1"
  local repo_root="${2:-}"

  mkdir -p "$perf_skill_home"

  if ! needs_runtime_install "$install_source" "$repo_root"; then
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

  ensure_package_source_prereqs "$install_source"

  if [[ -n "$repo_root" ]]; then
    if ! "$venv_python" -m pip install --quiet --disable-pip-version-check --editable "$repo_root"; then
      echo "error: failed to install perf-skill from local repo $repo_root into $venv_dir" >&2
      exit 2
    fi
  else
    if ! "$venv_python" -m pip install --quiet --disable-pip-version-check "$install_source"; then
      echo "error: failed to install perf-skill from $install_source into $venv_dir" >&2
      echo "hint: set PERF_SKILL_PACKAGE_SOURCE to a reachable package spec, git URL, wheel, sdist, or local path" >&2
      exit 2
    fi
  fi

  date -u +%FT%TZ > "$install_stamp"
  printf '%s\n' "$install_source" > "$install_source_file"
}

needs_runtime_install() {
  local install_source="$1"
  local repo_root="${2:-}"

  if [[ ! -x "$venv_python" ]]; then
    return 0
  fi

  if [[ ! -f "$install_stamp" ]]; then
    return 0
  fi

  if [[ ! -f "$install_source_file" ]]; then
    return 0
  fi

  if ! grep -Fqx "$install_source" "$install_source_file"; then
    return 0
  fi

  if [[ -n "$repo_root" && "$repo_root/pyproject.toml" -nt "$install_stamp" ]]; then
    return 0
  fi

  if [[ "$script_path" -nt "$install_stamp" ]]; then
    return 0
  fi

  if [[ -f "$skill_dir/SKILL.md" && "$skill_dir/SKILL.md" -nt "$install_stamp" ]]; then
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
detect_install_layout

openclaw_home="${OPENCLAW_HOME:-}"
if [[ -z "$openclaw_home" ]]; then
  if [[ -n "$detected_openclaw_home" ]]; then
    openclaw_home="$detected_openclaw_home"
  elif [[ -n "$workspace_root" ]]; then
    openclaw_home="$workspace_root/.openclaw"
  else
    openclaw_home="$HOME/.openclaw"
  fi
fi

perf_skill_home="${PERF_SKILL_HOME:-$openclaw_home/perf-skill}"
venv_dir="${PERF_SKILL_VENV_DIR:-$perf_skill_home/venv}"
venv_python="$venv_dir/bin/python3"
install_stamp="$perf_skill_home/.install-stamp"
install_source_file="$perf_skill_home/.install-source"
default_package_source="$(read_default_package_source)"
package_source="${PERF_SKILL_PACKAGE_SOURCE:-$default_package_source}"

repo_root=""
install_source="$package_source"
if repo_root="$(find_local_repo_root)"; then
  install_source="$repo_root"
fi

run_cwd="$(resolve_run_cwd "$repo_root")"
cd "$run_cwd"
ensure_runtime_env "$install_source" "$repo_root"

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