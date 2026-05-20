---
name: hardware-event-observe
description: 'Use when the user asks for Linux perf diagnosis or workflow orchestration from natural language. Examples of trigger phrases include English or Chinese requests about stress-ng load generation, pid or comm resolution, branch or cache analysis, system-wide perf, hotspots, symbols, FlameGraph, page-fault ranking, or staged memory diagnosis.'
argument-hint: '一句自然语言，例如：给 cpu50 的压力，然后探测 node 的 branch 10s 并告诉我结果、给 cpu50 的压力，然后探测 node 的 branch 10s 并告诉我热点、给 cpu50 的压力，然后探测 node 的 branch 10s 并生成图片、探测整个电脑的 branch 10s、寻找 page_fault 最多的程序、我的内存占用一直很高，我应该怎么测试'
---

# Hardware Event Observe

Use this skill when the user wants a Linux perf workflow from natural language
and does not want to manually decide every step such as load generation,
target discovery, `perf stat` versus `perf record -g`, system-wide mode,
or post-run analysis.

## Primary workflow

- Accept the user's sentence and classify it as one of these paths: target attach, target attach plus synthetic load, hotspot or symbol capture, FlameGraph or image generation, system-wide observation, top-offender discovery, or staged memory troubleshooting
- The model owns the orchestration and should choose the simplest tool that fits the request
- Resolve missing `pid` or `comm` automatically when possible. Use `pgrep`, `ps`, or `/proc` to find the target first, and only ask the user when multiple candidates remain or the action is disruptive
- Prefer `perf-skill` when it already covers the requested path. Prefer native `perf` plus shell tools when the user asks for system-wide mode, discovery across all processes, or a flow that the current CLI does not support
- Prefer Python-side summaries when the CLI can produce them. Otherwise synthesize the findings yourself and lead with the diagnosis instead of dumping raw counters
- Keep the CLI summary technical; if the user appears new to perf, add the plain-language explanation yourself in the final answer instead of expecting the tool output to contain it

## Decision priority

1. Decide the scope first: single process, single process under load, whole machine, offender discovery, or staged memory triage.
2. Decide the target next: resolve `pid` or `comm` automatically when possible, and ask the user only if multiple live candidates remain.
3. Decide the capture mode next: summary counters for `结果` or `诊断`, `perf record -g` for hotspots, symbols, callchains, FlameGraph, or hotspot-style images.
4. Decide the executor last: `perf-skill observe`, `perf-skill exercise`, or native shell plus native `perf`.

## Agent quick route

- Known `pid` or `comm` and the user wants counters, IPC, or a summary: use `perf-skill observe`; add `--summary` for diagnosis-oriented requests
- Generated load plus live counters only: use `perf-skill exercise`; do not force `exercise` if the user also wants hotspots, symbols, FlameGraph output, or `perf.data`
- Hotspots, symbols, callchains, FlameGraph, or hotspot-style images: use `perf record -g`, then parse or render with `perf-skill observe --data-in`
- Whole-machine observation or `page-fault` offender discovery: use native `perf ... -a`
- High-memory complaint with no target: start with `free`, `vmstat`, `ps`, or `smem`; only attach after the baseline points to a target
- Multiple matching PIDs for the same `comm`: ask once instead of picking one automatically
- Event-listing requests such as `列出 branch 相关事件` or `show cache events`: route them to the explicit `perf-skill events ...` subcommand instead of keeping observe-side parser sugar
- If the user does not know the exact event name and wants help choosing one, do a `list -> filter -> collect` workflow: list candidate events first, narrow them yourself, then collect with the smallest meaningful event set

## Event discovery flow

- Use this flow when the user asks broad questions such as `列出 branch 相关事件然后帮我挑合适的`, `有哪些 cache 事件适合排查热点`, or `先看看 page-fault 相关事件再决定采什么`
- Step 1: list candidate events with the explicit `perf-skill events ...` subcommand or native `perf list` when the user is browsing event families
- Step 2: filter those candidates yourself before collecting anything. Prefer the events that are portable, actionable, easy to explain, and already fit the tool's grouping model
- Step 3: collect with the smallest event set that still answers the user's question. Do not dump a huge list of candidate events back to the user and wait for them to build the command for you
- Step 4: explain why you picked the final set, especially if you filtered a large family down to one standard pair such as `branches + branch-misses` or `cache-references + cache-misses`

### Event filtering rules

- Prefer standard portable counters over obscure PMU-specific variants unless the user explicitly asked for the low-level variant
- Prefer pairs that the tool already understands well: `branches + branch-misses`, `cache-references + cache-misses`, and `instructions + cycles`
- Keep the final set small. If multiple events look similar, choose the one that best matches the user goal instead of collecting all of them
- If the goal is branch behavior, usually shortlist down to `branches` and `branch-misses`
- If the goal is cache behavior, usually shortlist down to `cache-references` and `cache-misses`
- If the goal is fault pressure or memory pressure, usually shortlist down to `page-faults`, and add `minor-faults` or `major-faults` only when that distinction matters
- If the request is system-wide discovery, prefer simple counters that are easy to summarize across the machine before moving to a deeper per-process follow-up
- If the final event set becomes too wide or too hardware-specific, simplify it before collecting instead of leaning on the parser to understand every listed synonym

## Grouping quick notes

- `group-mode auto` is the default. Keep `instructions + cycles` together, keep branch and cache pairs together when possible, and split only the failing group on retry.
- `group-mode always` means chunk the whole event set by `pmu-slots` even before perf fails. Use it when the user explicitly wants deterministic group layout.
- `group-mode off` means disable perf groups. Use it only when the user explicitly wants raw ungrouped counters or grouped retries would make the run harder to explain.
- `pmu-slots auto` keeps the default hardware budget, usually `4`. Software events and tracepoints do not consume that hardware counter budget.
- `--no-group-retry` is for users who explicitly do not want fallback behavior. Otherwise, let the CLI keep successful groups intact and only split the failing group further.
- Explain grouping choices in the skill response when the user is asking about workflow or interpretation, instead of adding more parser phrases just to surface the same runtime flags.

## Keep workflow logic in the skill

- Prefer the skill for workflow-only decisions such as PID discovery, ambiguity resolution, system-wide versus single-target scope, timeline SVG versus FlameGraph, and whether to use `exercise` or native `perf`.
- Event-listing is one of those workflow-only decisions. Prefer skill routing plus `perf-skill events` over adding more `observe` parser phrases.
- Event discovery followed by event filtering is also a workflow-only decision. Keep `list -> filter -> collect` here instead of trying to encode every discovery phrase into parser intents.
- Prefer Python code changes only when the runtime capability really changes. Do not add parser or CLI branches just because a new natural-language phrasing can be explained and orchestrated correctly in the skill.
- If the request can be satisfied by choosing better commands, better flags, or a clearer follow-up plan, keep that logic here instead of widening the parser surface.

## Extra support

- Understands omitted `comm=` forms such as `追踪 node 的 指令 和 周期`
- Understands direct software and tracepoint event names such as `cpu-clock`, `sched:sched_switch`, and `page-faults`
- Understands event aliases such as `branch`, `branchs`, `page_fault`, `page-fault`, `page_faults`, and `缺页`
- If neither `pid` nor `comm` is available and the request is not whole-machine or discovery-oriented, asks the user which process or service should be inspected before attaching
- Understands simple duration and sample-count hints such as `for 5 seconds`, `10 samples`, `10秒`, `持续 30 秒`, or `采 20 个样本`
- Understands load-generation phrasing such as `给 cpu50 的压力`; interpret that as a `stress-ng` CPU load request unless the user provides a different tool or stronger constraint
- Understands system-wide phrasing such as `整个电脑`, `全机`, `系统级`, `全系统`, or `整台机器`; route these requests to native `perf ... -a` when needed
- Understands image-export phrasing such as `探测20秒node的cycles并生成图像` or `生成10s内node的branchs的图像`, and will auto-pick a default `out/*.svg` path when `--svg-out` is omitted
- Understands vague slowdown reports such as `服务器有点卡`; in that case, propose a staged baseline check first and ask for the concrete process or service if no target is known yet
- Understands vague memory reports such as `我的内存占用一直很高`; in that case, start with a staged baseline and identify the hottest RSS or page-fault target before attaching
- Auto-renames generic `perf.data` requests to `out/comm_targetpid_event_data_time.data`
- Understands FlameGraph phrasing such as `追踪 node 的 cycles 并生成火焰图` or `解析 out/node.data 并生成火焰图`, auto-switches to `perf record -g` when needed, and auto-picks a default `*-flamegraph.svg` path when `--flamegraph-out` is omitted
- Understands hotspot and symbol phrasing such as `热点`, `热点信息`, `符号表`, `top symbol`, or `调用栈`; treat these as `perf record -g` or post-record parsing requests, not just `perf stat`
- Can export JSON summaries with trends, anomaly points, miss rates, hotspots, and top threads/callchains/symbols/comms
- Breaks callchain hotspots down per event, so `cycles` and `sched:sched_switch` can be reviewed separately
- Can continue `.data` parsing with `--report-stdio`, `--annotate-top`, or `--annotate-symbol` for a second analysis hop
- Can run `perf-skill exercise` with `stress-ng` or `ab` to create a load-and-observe loop
- Can list available events through the explicit `perf-skill events` subcommand, for example `perf-skill events branch` or `perf-skill events cache`
- Can start from a broad event-family listing, filter that list down to a portable shortlist, and then continue into collection without asking the user to assemble the final command
- Automatically bootstraps a dedicated Python runtime under the current workspace at `./.openclaw/perf-skill/venv` when the skill is installed into `./skills`, or under the matching toolkit home such as `~/.openclaw/perf-skill/venv`, `~/.ironclaw/perf-skill/venv`, or `~/.zeroclaw/perf-skill/venv` when the skill is installed globally
- Automatically bootstraps Brendan Gregg's FlameGraph repository under the active `PERF_SKILL_HOME`, for example `~/.openclaw/perf-skill/FlameGraph` by default or the matching IronClaw and ZeroClaw homes when launched from those toolkit layouts
- Auto-completes missing event pairs and auto-splits groups against a PMU slot limit
- In auto mode, prefers grouping event names that share a prefix, suffix, or namespace when there is a choice
- Can export CSV and SVG timeline artifacts during sampling
- Retries with smaller groups when perf returns retryable grouped-event failures

## When to Use

- The user says they want to observe `instructions`, `cycles`, `IPC`, `branches`, `branch-misses`, `cache-misses`, `page-faults`, or hotspots
- The user wants load generation hidden behind natural language, for example `给 cpu50 的压力`
- The user wants automatic target resolution from `comm`, not manual pid lookup
- The user wants system-wide observation such as `探测整个电脑的 branch 10s`
- The user wants to find the worst offender first, for example `寻找 page_fault 最多的程序`
- The user describes memory pressure in plain language and wants a test plan, not just a raw perf command
- The user is working inside this repository and wants the local CLI behavior when it fits

## Procedure

1. Parse the sentence and decide whether the request is target-scoped, load-plus-target, system-wide, discovery-first, or staged diagnosis.
2. If neither `pid` nor `comm` can be resolved and the request is not whole-machine, event-listing, offender-discovery, or memory-triage planning, ask the user which process or service should be inspected before running anything.
3. If the request includes synthetic load, treat it as a workflow decision owned by the model. Ask for confirmation when the load is disruptive.
4. If the request is process-scoped and no explicit pid is given, resolve the target before invoking the CLI. Use `pgrep -x`, `ps -C`, or `/proc`.
5. If the same `comm` matches multiple pids, show the candidate list and ask the user which pid to inspect. Do not let the CLI fail with a generic ambiguity error if you can resolve it one step earlier.
6. Use `perf-skill observe` for known-target live-stat runs, `.data` recording or parsing, `--summary`, timeline SVG export, or FlameGraph generation that stays inside the current CLI surface.
7. Use `perf-skill exercise` for `stress-ng` or `ab` plus live-stat observation. Pass the resolved target explicitly when the load tool is not the target process.
8. When the user asks for hotspots, symbols, callchains, `perf.data`, or a FlameGraph, use `perf record -g`. That includes phrases such as `告诉我热点信息`, `符号表`, `调用栈`, or `给我生成图片` when the picture is clearly hotspot-oriented.
9. When the user only asks for counters or a diagnosis summary, prefer `perf stat` and add `--summary` when the CLI path supports it.
10. If the user asks for system-wide observation, use native `perf ... -a` and summarize the important system-wide findings yourself.
11. If the user asks for the process with the most `page-faults`, run a short system-wide discovery pass on `page-faults`, rank by `comm` and `pid`, report the leader, and offer a second targeted run.
12. If the user says memory use is high but no target is known, start with a short baseline: overall memory, swap, page-fault pressure, and top RSS processes. Then recommend the narrowest next test rather than jumping straight to a deep perf capture.
13. If the user asks for an image, choose the right artifact: use `--svg-out` for timeline or trend charts, and use a FlameGraph SVG for hotspot pictures.
14. If the user asks to inspect or list available events, route that request to the explicit `perf-skill events` subcommand and pass any obvious filter terms there.
15. If the user needs help choosing from a listed family, do not stop at the listing step. Filter the candidate list yourself, choose the smallest useful event set, and continue into collection unless the user only asked to browse.
16. After `.data` parsing, report the top hotspots and top callchains first, summarize what they imply, and ask whether the user wants `perf annotate --stdio` on the hottest symbol.
17. After any live or record run, report the resolved target, whether `-g` or `-a` was used, the event set, duration, generated artifact paths, and the main diagnosis.
18. If `perf` reports permission, unsupported PMU, or `<not counted>` errors, surface that diagnostic directly.

## Runtime bootstrap

- The helper script auto-creates a virtual environment the first time it runs.
- If the skill lives under `./skills`, it treats that directory's parent as the active workspace and uses `./.openclaw/perf-skill/venv` by default.
- If the skill lives under `~/.openclaw/skills`, `~/.ironclaw/skills`, or `~/.zeroclaw/skills`, it uses the matching toolkit home under that same root by default.
- If a local repository checkout is available, it installs that checkout in editable mode so later source changes are picked up without rebuilding the environment.
- If no local checkout is available, it installs `perf-skill` from `PERF_SKILL_PACKAGE_SOURCE`, which defaults to the skill-bundled PyPI requirement in `package-requirement.txt`.
- FlameGraph rendering auto-clones Brendan Gregg's FlameGraph repository into the active `PERF_SKILL_HOME` on first use.
- If `pyproject.toml`, `SKILL.md`, or the helper script changes, or if the environment is missing dependencies, the helper reinstalls automatically on the next run.
- Override the default location with `OPENCLAW_HOME`, `IRONCLAW_HOME`, `ZEROCLAW_HOME`, or `PERF_SKILL_HOME` when a different shared path is required; override just the Python venv with `PERF_SKILL_VENV_DIR`, the FlameGraph checkout with `PERF_SKILL_FLAMEGRAPH_DIR`, or the Python package source with `PERF_SKILL_PACKAGE_SOURCE`.
- The machine still needs a working `python3 -m venv`; if that fails, install the system venv package first.

## Guardrails

Priority 1: correctness and safety.

- Prefer `--dry-run` before live attach when the user has not clearly asked to start sampling.
- Do not silently switch to another process if the requested `pid` or `comm` is invalid.
- If the user asks for disruptive load generation, confirm intent and required tooling before starting it.
- If a `comm` resolves to multiple pids, ask once instead of picking arbitrarily.

Priority 2: keep the measurement meaningful.

- Keep `instructions` and `cycles` in the event set so IPC remains available, unless the user explicitly wants a narrow event such as `page-faults` or a short system-wide discovery pass.
- Keep paired events together when possible, for example `branches + branch-misses`.
- Prefer `-g` whenever the user asks for hotspots, symbols, or callchains.
- Prefer `--summary` when the user wants diagnosis, comparison, or bottleneck explanation.
- When starting from event discovery, filter aggressively before collecting. Do not turn a broad event family listing into an oversized measurement set by default.

Priority 3: explain, do not dump.

- Lead with analysis, not raw output.
- Translate unfamiliar terms into a short plain-language metaphor in your own answer when the user appears new to perf.
- When you use native `perf` because the CLI does not cover the flow, say so briefly and keep the reasoning explicit.
- Use `python3`; this workspace shell may auto-correct `python` interactively.

## Examples

```bash
bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "追踪 node 的 指令 和 周期" --plain

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "追踪 node 的 cpu-clock 和 sched:sched_switch" --plain

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "追踪 node 的 cycles 并输出 perf.data" --seconds 10

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "追踪 node 的 cycles 并生成火焰图" --seconds 10

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "解析 out/node_targetpid4242_cycles_data_20260519T120000.data"

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "解析 out/node_targetpid4242_cycles_data_20260519T120000.data 并生成火焰图"

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace pid=16874 inst cycles summary" --summary

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "解析 out/node_targetpid16874_cycles_data_20260519T120000.data" --summary-out out/data-summary.json

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "解析 out/node_targetpid16874_cycles_data_20260519T120000.data" --summary --report-stdio

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "解析 out/node_targetpid16874_cycles_data_20260519T120000.data" --annotate-top

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
  exercise stress-ng --load-args "--cpu 4 --timeout 10" --summary

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  exercise ab "trace comm=nginx cache-misses" --load-args "-n 1000 -c 50 http://127.0.0.1:8080/" --summary

pgrep -x node

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  exercise stress-ng "trace pid=4242 branches branch-misses summary" \
  --load-args "--cpu 1 --cpu-load 50 --timeout 10" --seconds 10 --summary

perf stat -a -e branches,branch-misses -- sleep 10

perf record -a -g -e page-faults -- sleep 10

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  events branch

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  events cache

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  events branch

bash .github/skills/hardware-event-observe/scripts/run-observe.sh \
  "trace pid=16874 branches branch-misses for 10 seconds" --summary
```