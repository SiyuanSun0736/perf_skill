# perf-skill

perf-skill is a Linux CLI that turns a short declarative statement into a
ready-to-run `perf stat` session. It resolves the target process, enables sane
defaults for PMU collection, and streams a small terminal dashboard with IPC and
recent history charts.

## What it does

- Parses statements such as `trace comm=python pid=4242 inst cycles`
- Resolves the target process from `pid`, `comm`, or both
- Expands event aliases such as `inst -> instructions`
- Always injects `instructions` and `cycles` so IPC can be derived alongside any extra events
- Auto-completes missing paired counters such as `branches + branch-misses` and `cache-references + cache-misses`
- Auto-groups related events into perf groups so IPC, branch, and cache counters stay aligned
- Auto-splits groups against a PMU slot limit, with local hardware hints and vendor fallbacks
- Automatically retries with smaller groups when perf reports retryable grouped-event failures
- Starts `perf stat` with interval sampling and parses the live CSV output
- Can export time-series samples as CSV and stacked SVG charts
- Renders a rolling terminal dashboard with current counters and ASCII charts

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
perf-skill observe "trace comm=python pid=4242 inst cycles"
```

Use `--dry-run` first if you want to inspect the resolved request and generated
`perf` command without attaching to the process.

```bash
perf-skill observe "trace python 4242 inst" --dry-run
```

By default, the CLI uses `--group-mode auto` and emits `perf stat -e` groups such
as `{instructions,cycles,cache-misses}` or
`{instructions,cycles},{branches,branch-misses}`. This keeps related counters in
the same perf group without forcing everything into one oversized event set.

Use `--group-mode off` if you want the raw ungrouped event list, or
`--group-mode always` if you want every event list chunked into groups.

Use `--pmu-slots auto` to let the CLI pick a group size limit from local PMU
metadata when available, then fall back to vendor heuristics such as `4` for
common Intel cores and `6` for modern AMD Zen families. You can override this
with an explicit integer such as `--pmu-slots 4`.

If grouped collection fails with retryable `perf` diagnostics such as
`<not counted>` or grouped counter scheduling errors, the CLI now retries with
smaller `pmu-slots` values and finally falls back to ungrouped collection unless
you disable that behavior with `--no-group-retry`.

## Supported statement forms

The parser is intentionally narrow and predictable.

- `trace comm=python pid=4242 inst cycles`
- `observe python 4242 instructions`
- `追踪 comm=nginx pid=31337 inst cycles`
- `watch pid 9001 events=inst,cycles,cache-misses`

Recognized target keys:

- `pid`, `pid=1234`
- `comm`, `comm=python`

Recognized event aliases:

- `inst`, `instruction`, `instructions`
- `cycle`, `cycles`
- `branch-misses`, `branches`
- `cache-misses`, `cache-references`

Even if you request only `cache-misses` or `branches`, the tool still keeps
`instructions` and `cycles` in the perf event set so IPC remains available.

Even if you request only `branch-misses` or `cache-misses`, the CLI fills in the
paired counters it needs for a more interpretable timeline.

Auto grouping rules:

- `instructions` and `cycles` stay in the same core group
- `branches` and `branch-misses` are grouped together when both are present
- `cache-references` and `cache-misses` are grouped together when both are present
- Single leftover events are merged into an existing group when there is room

## Exporting traces

Write CSV samples during collection:

```bash
perf-skill observe "trace pid=4242 inst cycles cache-misses" \
	--samples 10 --plain --csv-out out/samples.csv
```

Write both CSV and SVG artifacts:

```bash
perf-skill observe "trace pid=4242 inst cycles branches" \
	--samples 20 --plain --csv-out out/samples.csv --svg-out out/timeline.svg
```

The CSV contains one row per interval sample. The SVG is a stacked time-series
report with one panel per metric plus IPC when available.

Use `--no-svg-legend` if you want a more compact SVG without the color legend.

## Notes

- Linux only. The tool shells out to `perf`.
- You may need lower `kernel.perf_event_paranoid` or elevated privileges.
- If `comm` matches multiple processes, the tool asks you to pin a `pid`.
- The terminal dashboard is ASCII only and works best in an interactive TTY.

## Development

Run the unit tests:

```bash
python -m unittest discover -s tests
```

## IDE usage

This repository also includes a Copilot Skill at
`.github/skills/hardware-event-observe/` so you can trigger the local CLI from
 VS Code chat with a natural-language request.

Example invocations:

```text
/hardware-event-observe 追踪 comm=node pid=16874 的 inst 和 cycles
/hardware-event-observe observe pid=16874 cache-misses branches
/hardware-event-observe observe pid=16874 branch-misses --samples 10 --csv-out out/node.csv --svg-out out/node.svg
```

The skill delegates to the local helper script:

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
	"trace pid=16874 inst cycles" --samples 5 --plain
```

The script keeps the invocation inside this repository and uses `python3` with
`PYTHONPATH=src`, which matches the environment validated in this workspace.

