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
- Can auto-clone Brendan Gregg's FlameGraph repository and render FlameGraph SVGs from recorded `.data` files
- Can continue `.data` analysis with `perf report --stdio` and `perf annotate --stdio`
- Can launch `stress-ng` or `ab` through the `exercise` subcommand and observe either the resolved target or the load process itself during the run
- Can generate Python-side summaries with trends, miss ratios, expert diagnosis, and top perf.data hotspots
- Can export those summaries as structured JSON for later automation
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

If the statement asks for a FlameGraph, or if you pass `--flamegraph-out`, the
CLI also switches to `perf record -g`, bootstraps
`https://github.com/brendangregg/FlameGraph.git` under
`~/.openclaw/perf-skill/FlameGraph` on first use, and writes a FlameGraph SVG:

```bash
perf-skill observe "追踪 node 的 cycles 并生成火焰图" --seconds 10
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --flamegraph-out out/node-flamegraph.svg
```

If you want to parse an existing `.data` file, the CLI can proxy `perf script`:

```bash
perf-skill observe "解析 out/node_targetpid4242_cycles_data_20260519T120000.data"
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data
```

If you want a second-hop analysis step after the Python-side `.data` summary,
you can now append `perf report --stdio` or auto-run `perf annotate --stdio`
for the hottest parsed symbol:

```bash
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --summary --report-stdio
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --annotate-top
perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --annotate-symbol 'v8::Function+0x10'
```

If you want analysis that goes beyond a single `perf` command, enable the
Python summary layer. It can compute post-run averages, peaks, trends, derived
ratios such as branch-miss rate and cache-miss rate, automatically flag anomaly
points such as sudden IPC drops or miss-rate surges, turn those signals into
expert diagnosis plus next-step recommendations, and summarize `.data`
artifacts by top events, threads, callchains, comms, symbols, and ranked hotspots:

```bash
perf-skill observe "trace pid=4242 inst cycles" --summary
perf-skill observe "trace pid=4242 branches branch-misses" --summary-out out/summary.json
perf-skill observe "解析 out/node_targetpid4242_cycles_data_20260519T120000.data" --summary
```

For live observations, anomaly lines are emitted in the summary with the sample
timestamp where the deviation was detected, and the summary now also emits
`insight` and `next-step` lines so the result is easier to act on.
Plain and dashboard output now also mark those anomalies as they happen.
For `.data` parsing, thread-level aggregation is shown as `top-thread` entries
keyed by `comm pid/tid`, `top-callchain` entries summarize stacked perf script
frames, `top-callchain[event]` further breaks those stacks down per event such
as `cycles` or `sched:sched_switch`, and `hotspot` lines highlight the symbols
with the largest sample share. The dashboard also keeps an alert summary with a
total anomaly count, a recent time-window count, and the last alert timestamp.
If you want novice-friendly metaphors or term translation, keep that in the AI
layer or skill response instead of expecting the CLI summary itself to render it.

If you want a single command for load generation plus observation, use the new
`exercise` subcommand. It launches `stress-ng` or `ab`, then observes either the
resolved target or, when no target is given, the load process itself. The final
output includes both the load-tool result and the perf summary:

```bash
perf-skill exercise stress-ng --load-args "--cpu 4 --timeout 10" --summary
perf-skill exercise ab "trace comm=nginx cache-misses" --load-args "-n 1000 -c 50 http://127.0.0.1:8080/" --summary
```

`exercise` is best for `load generation + live perf stat`. If you really want
hotspots, symbols, FlameGraphs, whole-machine observation, page-fault ranking,
or discovery before choosing a target, do not force the whole workflow into the
Python CLI. It is usually better to use `pgrep`, `ps`, `free`, `vmstat`,
`smem`, or native `perf` for the discovery and recording steps, then hand the
resolved target or recorded `.data` artifact back to `perf-skill` for summary,
reporting, or rendering.

## AI/agent routing quick reference

This table describes how an AI or human operator should route the workflow. It
is broader than the narrow statement parser. Use `perf-skill` when it fits, and
use shell plus native `perf` when the workflow needs discovery, system-wide
scope, or a recording step that the current CLI does not cover end-to-end.

| User intent | Preferred path | Keep outside the Python CLI |
| --- | --- | --- |
| Known target, counters, IPC, or summary | `perf-skill observe` | Nothing special |
| Known target under generated load, live counters only | `perf-skill exercise` | Let the AI decide the `stress-ng` or `ab` arguments |
| Hotspots, symbols, callchains, FlameGraphs, or hotspot-style images | `perf record -g` + `perf-skill observe --data-in` | Recording and multi-step orchestration |
| Whole-machine branch, cache, or page-fault observation | native `perf ... -a` | system-wide scope |
| Find the process with the most page faults | native `perf` discovery first, then `perf-skill` summary | offender discovery |
| Memory stays high and no target is known yet | `free`, `vmstat`, `ps`, `smem`, then `perf stat` or `perf record -g` | baseline and target discovery |
| One `comm` matches multiple PIDs | `pgrep -ax` or `ps -C` first, then ask the user | PID disambiguation |

## Scenario-driven workflows

These workflows are meant for both humans and agents. The goal is to keep the
workflow realistic instead of pretending every request should be compressed into
one parser statement.

1. `Generate CPU50 load, then probe node branch for 10s and tell me the result`

	This is a `load + known process + summary counters` flow. Resolve the `node`
	PID first. If there is only one match, `exercise` is the simplest path.

	```bash
	pgrep -x node
	perf-skill exercise stress-ng "trace pid=4242 branches branch-misses" \
	  --load-args "--cpu 1 --cpu-load 50 --timeout 10" \
	  --seconds 10 --summary
	```

2. `Generate CPU50 load, then probe node branch for 10s and tell me hotspots or symbols`

	This is a `load + known process + hotspots` flow, so switch to
	`perf record -g`. `exercise` does not cover that chain today. Start the load
	with shell, record with native `perf`, then hand the `.data` file back to
	`perf-skill` for summary, `perf report --stdio`, or `perf annotate`.

	```bash
	pgrep -x node
	stress-ng --cpu 1 --cpu-load 50 --timeout 12 &
	perf record -g -o out/node-branches.data -e branches,branch-misses -p 4242 -- sleep 10
	perf-skill observe --data-in out/node-branches.data --summary --report-stdio
	perf-skill observe --data-in out/node-branches.data --annotate-top
	```

3. `Generate CPU50 load, then probe node branch for 10s and generate an image`

	Decide whether the user wants a trend chart or a hotspot picture. For branch
	trends, export a timeline SVG. For hotspot pictures, record `.data` and emit
	a FlameGraph.

	```bash
	pgrep -x node
	perf-skill exercise stress-ng "trace pid=4242 branches branch-misses" \
	  --load-args "--cpu 1 --cpu-load 50 --timeout 10" \
	  --seconds 10 --svg-out out/node-branches.svg

	stress-ng --cpu 1 --cpu-load 50 --timeout 12 &
	perf record -g -o out/node-branches.data -e branches,branch-misses -p 4242 -- sleep 10
	perf-skill observe --data-in out/node-branches.data --flamegraph-out out/node-branches-flamegraph.svg
	```

4. `Generate CPU50 load, then probe whole-machine branch for 10s`

	This is system-wide observation. Do not guess a PID first.

	```bash
	stress-ng --cpu 1 --cpu-load 50 --timeout 12 &
	perf stat -a -e branches,branch-misses -- sleep 10
	```

5. `Find the program with the most page faults`

	This is offender discovery. Run a short system-wide recording first, then use
	the Python summary to inspect `top-comm`, `top-thread`, and hotspots.

	```bash
	perf record -a -g -o out/pagefaults.data -e page-faults -- sleep 10
	perf-skill observe --data-in out/pagefaults.data --summary
	```

6. `Memory usage stays high. How should I test it?`

	Start with a baseline before deciding whether this is even a `perf` question.
	Separate whole-machine memory pressure, swap activity, page-fault pressure,
	and a single process with outsized RSS. Only then choose `perf stat` or
	`perf record -g`.

	```bash
	free -h
	vmstat 1 5
	ps -eo pid,comm,rss,%mem --sort=-rss | head
	smem -rk | head
	perf stat -p 4242 -e page-faults,minor-faults,major-faults -- sleep 10
	```

7. `I said node, but the machine has multiple node processes`

	Do not let the CLI fail on ambiguity and do not pick a PID silently. Show the
	candidates and ask once.

	```bash
	pgrep -ax node
	ps -C node -o pid,cmd
	```

8. `I already have perf.data. Continue with hotspots, FlameGraph, or symbols`

	This is a `.data` second-hop analysis flow. Reuse the artifact instead of
	attaching again.

	```bash
	perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --summary --report-stdio
	perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --annotate-top
	perf-skill observe --data-in out/node_targetpid4242_cycles_data_20260519T120000.data --flamegraph-out out/node-flamegraph.svg
	```

9. `The server feels slow, but I do not yet know which process to inspect`

	This is target discovery. Inspect CPU, memory, and listeners first. Only
	attach once the target is clear.

	```bash
	ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head
	ps -eo pid,comm,rss,%mem --sort=-rss | head
	ss -lntp | head
	perf-skill events branch
	```

If you only want to inspect available events, use `perf list` through the CLI:

```bash
perf-skill events
perf-skill events cache
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
perf-skill exercise --help
```

## Supported statement forms

The parser is intentionally narrow and predictable. The `AI/agent routing quick
reference` and `Scenario-driven workflows` sections above can be broader than
the parser itself, because workflow orchestration is allowed to combine shell,
native `perf`, and `perf-skill` instead of forcing every request into one
statement.

- `trace comm=python pid=4242 inst cycles`
- `observe python 4242 instructions`
- `observe node instructions`
- `observe node cpu-clock sched:sched_switch`
- `追踪 node 的 cycles 并输出 perf.data`
- `追踪 node 的 cycles 并生成火焰图`
- `解析 out/node_targetpid4242_cycles_data_20260519T120000.data`
- `解析 out/node_targetpid4242_cycles_data_20260519T120000.data 并生成火焰图`
- `trace pid=4242 inst cycles summary`
- `trace pid=4242 inst cycles for 5 seconds`
- `observe pid=4242 cache-misses 10 samples`
- `追踪 comm=nginx pid=31337 inst cycles`
- `追踪 node 的 指令 和 周期`
- `我要追踪node20秒内的cycles`
- `探测20秒node的cycles并生成图像`
- `生成10s内node的branchs的图像`
- `追踪 pid=31337 的 inst 和 cycles，采样10次`
- `追踪 node 持续 30 秒，采 20 个样本`
- `watch pid 9001 events=inst,cycles,cache-misses`

Event listing is intentionally explicit now. Use `perf-skill events`, `perf-skill events cache`, or let the skill route a natural-language event-listing request to that subcommand instead of widening the parser again.

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

Write a Python-generated JSON summary:

```bash
perf-skill observe "trace pid=4242 inst cycles" --summary-out out/summary.json
perf-skill observe --data-in out/python_targetpid4242_cycles_data_20260519T120000.data --summary-out out/data-summary.json
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
`.github/workflows/release.yml`. Pushing a tag such as `v1.0.0` builds the wheel
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
PYTHONPATH=src python3 scripts/release/validate_tag.py v1.0.0
PYTHONPATH=src python3 scripts/release/generate_changelog.py --tag v1.0.0 --output /tmp/release-notes.md
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
/hardware-event-observe 解析 out/node_targetpid16874_cycles_data_20260519T120000.data 并生成火焰图
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
editable mode with its Python dependencies. FlameGraph rendering also
auto-clones Brendan Gregg's FlameGraph repository under
`~/.openclaw/perf-skill/FlameGraph` on first use. You can override the shared
install path with `OPENCLAW_HOME` or `PERF_SKILL_HOME`, the virtual environment
path with `PERF_SKILL_VENV_DIR`, and the FlameGraph checkout path with
`PERF_SKILL_FLAMEGRAPH_DIR`.

