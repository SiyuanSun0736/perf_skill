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
- Starts `perf stat` with interval sampling and parses the live CSV output
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
```

The skill delegates to the local helper script:

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
	"trace pid=16874 inst cycles" --samples 5 --plain
```

The script keeps the invocation inside this repository and uses `python3` with
`PYTHONPATH=src`, which matches the environment validated in this workspace.

