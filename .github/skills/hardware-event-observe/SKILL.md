---
name: hardware-event-observe
description: 'Observe Linux PMU hardware counters from a natural-language request. Use when the user wants to trace a pid or comm with perf stat, instructions, cycles, IPC, branch-misses, cache-misses, or cache-references. Trigger phrases include: 追踪哪个comm的哪个pid的inst或者cycles, observe perf hardware events, trace pid with IPC.'
argument-hint: '一句自然语言，例如：追踪 comm=node pid=16874 的 inst 和 cycles'
---

# Hardware Event Observe

Use this skill when the user wants a Linux process-level hardware event session
without manually writing `perf stat` arguments.

## What this skill does

- Accepts a natural-language statement that describes `pid`, `comm`, and events
- Delegates to the local `perf-skill` CLI in this repository
- Supports a dry run to inspect the generated `perf stat` command
- Supports live sampling with IPC derived from `instructions / cycles`
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
2. If the target is ambiguous or the user wants inspection only, run a dry run first with [run-observe.sh](./scripts/run-observe.sh).
3. For a real attach, run [run-observe.sh](./scripts/run-observe.sh) with the statement and any needed flags such as `--plain`, `--samples`, `--dry-run`, `--csv-out`, `--svg-out`, `--pmu-slots`, `--no-group-retry`, or `--no-svg-legend`.
4. Report the resolved target, the events, the generated `perf` command for dry runs, and the resulting IPC for live runs.
5. If `perf` reports permission, unsupported PMU, or `<not counted>` errors, surface that diagnostic directly.

## Guardrails

- Prefer `--dry-run` before live attach when the user has not clearly asked to start sampling.
- Do not silently switch to another process if the requested `pid` or `comm` is invalid.
- Keep `instructions` and `cycles` in the event set so IPC remains available.
- Keep paired events together when possible, for example `branches + branch-misses`.
- Use `python3`; this workspace shell may auto-correct `python` interactively.

## Examples

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace comm=node pid=16874 inst cycles" --dry-run

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "observe pid=16874 cache-misses branches" --samples 5 --plain

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "observe pid=16874 branch-misses" --samples 10 --csv-out out/node.csv --svg-out out/node.svg
```
