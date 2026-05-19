# perf-skill

[English](./README.md) | [简体中文](./README-CN.md)

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
- Can switch to `perf record` and write a renamed `.data` artifact when requested
- Can parse an existing `.data` file via `perf script -i`
- Can export time-series samples as CSV and stacked SVG charts
- Renders a rolling terminal dashboard with current counters and ASCII charts

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
perf-skill observe "trace comm=python pid=4242 inst cycles"
```

For editable local development, use `pip install -e .[dev]` instead.

Use `--dry-run` first if you want a simulated preview of the resolved request and
generated `perf` command without attaching to the process. This preview is
implemented by `perf-skill`; native `perf` does not provide a `--dry-run`
option.

```bash
perf-skill observe "trace python 4242 inst" --dry-run
```

By default, the CLI uses `--group-mode auto` and emits `perf stat -e` groups such
as `{instructions,cycles,cache-misses}` or
`{instructions,cycles},{branches,branch-misses}`. This keeps related counters in
the same perf group without forcing everything into one oversized event set.

You can stop a live run after either a fixed sample count or a fixed duration:

```bash
perf-skill observe "trace pid=4242 inst cycles" --samples 10 --plain
perf-skill observe "trace pid=4242 inst cycles" --seconds 5 --plain
```

The statement parser also understands short natural-language hints such as
`for 5 seconds`, `10 samples`, `10秒`, `采样10次`, `持续 30 秒`, or
`采 20 个样本`.

If the statement asks to generate an image or chart, the CLI also enables SVG
export automatically and picks a default path under `out/`, for example:

```bash
perf-skill observe "探测20秒node的cycles并生成图像"
perf-skill observe "生成10s内node的branchs的图像"
```

If the statement asks for `perf.data`, the CLI switches to `perf record` and
auto-picks a renamed output path like
`out/node_targetpid4242_cycles_data_20260519T120000.data` when you did not pass
`--data-out` explicitly:

```bash
perf-skill observe "追踪 node 的 cycles 并输出 perf.data" --seconds 10
```

If you want to parse an existing `.data` file, the CLI can proxy `perf script`:

```bash
perf-skill observe "解析 out/node_targetpid4242_cycles_data_20260519T120000.data"
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data
```

If you only want to inspect available events, use `perf list` through the CLI:

```bash
perf-skill events
perf-skill events cache
perf-skill observe "show cache events"
```

Use `--group-mode off` if you want the raw ungrouped event list, or
`--group-mode always` if you want every event list chunked into groups.

Use `--pmu-slots auto` to keep the default hardware grouping budget at `4`
slots. Cache and branch families stay grouped when possible, while software
events such as `cpu-clock` and tracepoints such as `sched:sched_switch` do not
consume those hardware slots. You can still override the budget with an
explicit integer such as `--pmu-slots 4`.

The parser also accepts these event names directly in natural-language
statements, for example:

```bash
perf-skill observe "trace node cpu-clock sched:sched_switch" --plain
perf-skill observe "追踪 node 的 cpu-clock 和 sched:sched_switch" --plain
```

If grouped collection fails with retryable `perf` diagnostics such as
`<not counted>` or grouped counter scheduling errors, the CLI now retries with
smaller `pmu-slots` values and finally falls back to ungrouped collection unless
you disable that behavior with `--no-group-retry`. Successful groups keep their
current layout while only the failing group is split further.

You can inspect the full CLI reference with:

```bash
perf-skill --help
perf-skill observe --help
```

## Supported statement forms

The parser is intentionally narrow and predictable.

- `trace comm=python pid=4242 inst cycles`
- `observe python 4242 instructions`
- `observe node instructions`
- `observe node cpu-clock sched:sched_switch`
- `追踪 node 的 cycles 并输出 perf.data`
- `解析 out/node_targetpid4242_cycles_data_20260519T120000.data`
- `trace pid=4242 inst cycles for 5 seconds`
- `observe pid=4242 cache-misses 10 samples`
- `追踪 comm=nginx pid=31337 inst cycles`
- `追踪 node 的 指令 和 周期`
- `我要追踪node20秒内的cycles`
- `探测20秒node的cycles并生成图像`
- `生成10s内node的branchs的图像`
- `追踪 pid=31337 的 inst 和 cycles，采样10次`
- `追踪 node 持续 30 秒，采 20 个样本`
- `列出 branch 相关事件`
- `支持哪些 PMU 事件`
- `查看 cache 相关事件`
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
- Names that share a strong prefix, suffix, or namespace are preferred in the same group when there is a choice
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

SVG charts are rendered with matplotlib instead of hand-written XML, so the
output is easier to read and closer to a normal plotting workflow.

Use `--no-svg-legend` if you want a more compact SVG without the color legend.

Write a renamed `perf.data` artifact with `perf record`:

```bash
perf-skill observe "trace pid=4242 inst cycles" --data-out out/python_targetpid4242_cycles_data_20260519T120000.data --seconds 10
```

Parse a recorded `.data` artifact with `perf script`:

```bash
perf-skill observe --data-in out/python_targetpid4242_cycles_data_20260519T120000.data
```

## Packaging and releases

Build a local wheel and sdist:

```bash
python -m pip install -e .[dev]
python -m build
```

Install the generated wheel locally:

```bash
pip install dist/perf_skill-*.whl
```

This repository includes a tag-driven GitHub Actions workflow at
`.github/workflows/release.yml`. Pushing a tag such as `v0.5.1` builds the wheel
and sdist, validates that the tag matches the package version, generates a
changelog from commits since the previous tag, uploads the built artifacts, and
attaches them to a GitHub release.

The release workflow uses:

- `scripts/release/validate_tag.py` to assert `vX.Y.Z` matches `perf_skill.__version__`
- `scripts/release/generate_changelog.py` to build release notes from the git history between tags

If you want to bump the package version references before tagging, use:

```bash
python3 scripts/release/bump_version.py 0.6.0 --dry-run
python3 scripts/release/bump_version.py 0.6.0
```

To enable PyPI publishing, configure a trusted publisher for this repository on
PyPI and set the repository variable `PUBLISH_PYPI=true`. The workflow will then
publish the same `dist/` artifacts to PyPI after a tagged release build.

You can also run the release helpers locally:

```bash
PYTHONPATH=src python3 scripts/release/validate_tag.py v0.5.1
PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v0.5.1 --output /tmp/release-notes.md
```

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
an auto-bootstrapped virtual environment under `~/.openclaw/perf-skill/venv`.
On the first run, it creates that environment and installs this repository in
editable mode with its Python dependencies. You can override the install path
with `OPENCLAW_HOME`, `PERF_SKILL_HOME`, or `PERF_SKILL_VENV_DIR`.

