---
name: hardware-event-observe
description: 'Observe Linux PMU hardware counters from a natural-language request. Use when the user wants to trace a pid or comm with perf stat, instructions, cycles, IPC, branch-misses, cache-misses, or cache-references. Trigger phrases include: 追踪哪个comm的哪个pid的inst或者cycles, observe perf hardware events, trace pid with IPC.'
argument-hint: '一句自然语言，例如：追踪 node 的 指令 和 周期、我要追踪node20秒内的cycles、探测20秒node的cycles并生成图像'
---

# Hardware Event Observe

Use this skill when the user wants a Linux process-level hardware event session
without manually writing `perf stat` arguments.

## What this skill does

- Accepts a natural-language statement that describes `pid`, `comm`, and events
- Delegates to the local `perf-skill` CLI in this repository
- Supports a simulated dry run to inspect the generated `perf stat` command
- Supports live sampling with IPC derived from `instructions / cycles`
- Understands omitted `comm=` forms such as `追踪 node 的 指令 和 周期`
- Understands simple duration and sample-count hints such as `for 5 seconds`, `10 samples`, `10秒`, `持续 30 秒`, or `采 20 个样本`
- Understands image-export phrasing such as `探测20秒node的cycles并生成图像` or `生成10s内node的branchs的图像`, and will auto-pick a default `out/*.svg` path when `--svg-out` is omitted
- Can list available events through `perf list`, for example when the user asks `列出 branch 相关事件` or `支持哪些 PMU 事件`
- Automatically bootstraps a dedicated Python runtime under `~/.openclaw/perf-skill/venv` on machines that do not already have the environment prepared
- Auto-completes missing event pairs and auto-splits groups against a PMU slot limit
- Can export CSV and SVG timeline artifacts during sampling
- Retries with smaller groups when perf returns retryable grouped-event failures

## When to Use

- The user says they want to observe `instructions`, `cycles`, or `IPC`
- The user describes a target process by `pid`, `comm`, or both
- The user wants `perf` command generation hidden behind natural language
- The user is working inside this repository and wants the local CLI behavior

## Procedure

1. Take the user's sentence as the observation statement.
2. If the target is ambiguous or the user wants inspection only, run a dry run first with [run-observe.sh](./scripts/run-observe.sh). When you report the result, be explicit that this is a `perf-skill` preview; native `perf` does not support `--dry-run`.
3. For a real attach, run [run-observe.sh](./scripts/run-observe.sh) with the statement and any needed flags such as `--plain`, `--samples`, `--dry-run`, `--csv-out`, `--svg-out`, `--pmu-slots`, `--no-group-retry`, or `--no-svg-legend`.
4. Use `--seconds` when the user wants a fixed duration and `--samples` when the user wants a fixed sample count. The statement itself may already contain those hints.
5. If the user asks to inspect or list available events, run the same helper with a statement such as `查看 cache 相关事件`; the CLI will delegate to `perf list`.
6. Report the resolved target, the events, the generated `perf` command for dry runs, and the resulting IPC for live runs.
7. If `perf` reports permission, unsupported PMU, or `<not counted>` errors, surface that diagnostic directly.

## Runtime bootstrap

- The helper script auto-creates a virtual environment in `~/.openclaw/perf-skill/venv` the first time it runs.
- It installs the local repository in editable mode, so later source changes in this repo are picked up without rebuilding the environment.
- If `pyproject.toml` changes or the environment is missing dependencies, the helper reinstalls automatically on the next run.
- Override the default location with `OPENCLAW_HOME`, `PERF_SKILL_HOME`, or `PERF_SKILL_VENV_DIR` when a different shared path is required.
- The machine still needs a working `python3 -m venv`; if that fails, install the system venv package first.

## Guardrails

- Prefer `--dry-run` before live attach when the user has not clearly asked to start sampling.
- Do not silently switch to another process if the requested `pid` or `comm` is invalid.
- Keep `instructions` and `cycles` in the event set so IPC remains available.
- Keep paired events together when possible, for example `branches + branch-misses`.
- Use `python3`; this workspace shell may auto-correct `python` interactively.

## Examples

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "追踪 node 的 指令 和 周期" --plain

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "我要追踪node20秒内的cycles" --plain

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "探测20秒node的cycles并生成图像"

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "生成10s内node的branchs的图像"

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace comm=node pid=16874 inst cycles" --dry-run

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "observe pid=16874 cache-misses branches for 5 seconds" --plain

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "observe pid=16874 branch-misses" --samples 10 --csv-out out/node.csv --svg-out out/node.svg

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "列出 branch 相关事件"

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "查看 cache 相关事件"
```
