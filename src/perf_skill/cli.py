from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import time

from perf_skill import __version__
from perf_skill.export import CsvSampleWriter, write_svg_report
from perf_skill.models import ObservationError, PerfSample, PerfStatError
from perf_skill.parser import build_request, parse_observation_statement
from perf_skill.perf import build_perf_command, build_retry_plans, detect_pmu_slot_limit, format_retry_plan, plan_event_groups, stream_perf_samples
from perf_skill.processes import resolve_target
from perf_skill.ui import DashboardRenderer


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass


ROOT_EPILOG = """Examples:
    perf-skill observe \"trace pid=4242 inst cycles\" --dry-run
    perf-skill observe \"追踪 node 的 指令 和 周期\" --plain
    perf-skill observe \"trace pid=4242 inst cycles for 5 seconds\" --plain
    perf-skill observe \"我要追踪node20秒内的cycles\" --plain
    perf-skill observe \"探测20秒node的cycles并生成图像\"
    perf-skill observe \"trace comm=node branch-misses cache-misses\" --samples 10 --plain
    perf-skill observe \"trace pid=4242 inst cycles\" --csv-out out/samples.csv --svg-out out/timeline.svg
    perf-skill events cache

Use 'perf-skill observe --help' for observe-specific examples and advanced grouping flags.
"""


OBSERVE_EPILOG = """Examples:
    perf-skill observe \"trace pid=4242 inst cycles\" --dry-run
    perf-skill observe \"追踪 node 的 指令 和 周期\" --plain
    perf-skill observe \"trace pid=4242 inst cycles for 5 seconds\" --plain
    perf-skill observe \"我要追踪node20秒内的cycles\" --plain
    perf-skill observe \"探测20秒node的cycles并生成图像\"
    perf-skill observe \"生成10s内node的branchs的图像\"
    perf-skill observe \"trace pid=4242 branch-misses cache-misses\" --pmu-slots 2
    perf-skill observe \"trace comm=node inst cycles cache-misses\" --samples 20 --plain --csv-out out/node.csv
    perf-skill observe \"列出 branch 相关事件\"
    perf-skill observe \"查看 cache 相关事件\"

Grouping behavior:
    - auto: keep related counters together and split only failing groups on retry
    - always: chunk the full event set by PMU slot count
    - off: disable perf groups entirely
"""


EVENTS_EPILOG = """Examples:
    perf-skill events
    perf-skill events cache
    perf-skill events branch-misses
    perf-skill observe \"支持哪些 PMU 事件\"
"""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return 130
    except (ObservationError, PerfStatError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perf-skill",
        description="Declarative Linux PMU observation on top of perf stat",
        epilog=ROOT_EPILOG,
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    observe_parser = subparsers.add_parser(
        "observe",
        help="parse a statement, resolve a target, and stream perf counters",
        description="Resolve a pid or comm from a short statement, then sample perf hardware counters with adaptive grouping.",
        epilog=OBSERVE_EPILOG,
        formatter_class=HelpFormatter,
    )
    observe_parser.add_argument(
        "statement",
        nargs="?",
        default="",
        help="declarative statement such as 'trace comm=python pid=4242 inst cycles' or '查看 cache 相关事件'",
    )
    observe_parser.add_argument("--pid", type=int, help="explicit pid override")
    observe_parser.add_argument("--comm", help="explicit process comm override")
    observe_parser.add_argument(
        "--events",
        help="comma-separated event override such as inst,cycles,cache-misses; missing partner counters are auto-completed",
    )
    observe_parser.add_argument(
        "--interval-ms",
        type=int,
        default=1000,
        help="perf interval in milliseconds",
    )
    observe_parser.add_argument(
        "--history",
        type=int,
        default=30,
        help="number of recent samples to keep in the dashboard",
    )
    observe_parser.add_argument(
        "--samples",
        type=int,
        help="stop after collecting N samples",
    )
    observe_parser.add_argument(
        "--seconds",
        type=int,
        help="stop after collecting for N seconds",
    )
    observe_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show a simulated preview of the resolved request and perf command without running perf",
    )
    observe_parser.add_argument(
        "--plain",
        action="store_true",
        help="disable the dashboard and print one line per sample",
    )
    observe_parser.add_argument(
        "--group-mode",
        choices=("auto", "always", "off"),
        default="auto",
        help="event grouping strategy: auto keeps related counters together and retries only failing groups, always chunks the whole set, off disables grouping",
    )
    observe_parser.add_argument(
        "--pmu-slots",
        default="auto",
        help="PMU slot limit for group splitting; use 'auto' to read local hints and vendor heuristics before adaptive retries",
    )
    observe_parser.add_argument(
        "--csv-out",
        help="write collected samples to a CSV file as they arrive",
    )
    observe_parser.add_argument(
        "--svg-out",
        help="write a stacked SVG time-series report after sampling finishes",
    )
    observe_parser.add_argument(
        "--svg-legend",
        dest="svg_legend",
        action="store_true",
        help="include a color legend in the SVG export",
    )
    observe_parser.add_argument(
        "--no-svg-legend",
        dest="svg_legend",
        action="store_false",
        help="omit the color legend from the SVG export",
    )
    observe_parser.add_argument(
        "--no-group-retry",
        dest="group_retry",
        action="store_false",
        help="disable adaptive retries that split groups further after retryable perf failures",
    )
    observe_parser.set_defaults(svg_legend=True, group_retry=True)
    observe_parser.set_defaults(handler=_handle_observe)

    events_parser = subparsers.add_parser(
        "events",
        help="list available perf events using perf list",
        description="Proxy to perf list with optional filters so you can inspect available events before attaching.",
        epilog=EVENTS_EPILOG,
        formatter_class=HelpFormatter,
    )
    events_parser.add_argument(
        "query",
        nargs="*",
        help="optional perf list filters such as cache, branch-misses, or instructions",
    )
    events_parser.set_defaults(handler=_handle_events)
    return parser


def _handle_observe(args: argparse.Namespace) -> int:
    parsed = parse_observation_statement(args.statement)
    effective_dry_run = args.dry_run or parsed.wants_dry_run
    effective_samples = _resolve_limit(args.samples, parsed.sample_count, label="samples")
    effective_seconds = _resolve_limit(args.seconds, parsed.duration_sec, label="seconds")
    event_filters = _merge_filters(
        tuple(args.events.split(",")) if args.events else (),
        parsed.event_filters,
    )

    if parsed.wants_event_list:
        return _handle_event_listing(event_filters, dry_run=effective_dry_run)

    extra_events = args.events.split(",") if args.events else None
    pmu_slots = _parse_pmu_slots_arg(args.pmu_slots)
    resolved_pmu_slots = detect_pmu_slot_limit() if pmu_slots is None else pmu_slots
    request = build_request(
        args.statement,
        pid=args.pid,
        comm=args.comm,
        extra_events=extra_events,
        interval_ms=args.interval_ms,
        history_size=args.history,
        parsed=parsed,
    )
    target = resolve_target(request)
    effective_svg_out = _resolve_svg_out(args.svg_out, request, target, parsed=parsed)
    retry_plans = build_retry_plans(
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
        retry_grouping=args.group_retry,
    )
    command = build_perf_command(
        request,
        target,
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
    )
    event_groups = plan_event_groups(
        request.events,
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
    )

    if effective_dry_run:
        print("preview   : simulated dry-run only; perf itself has no --dry-run option")
        print(f"statement : {request.statement or '<empty>'}")
        print(f"target    : pid={target.pid} comm={target.comm}")
        print(f"events    : {', '.join(request.events)}")
        print(f"group-mode: {args.group_mode}")
        print(f"pmu-slots : {args.pmu_slots} (resolved {resolved_pmu_slots})")
        print(f"groups    : {' | '.join(', '.join(group) for group in event_groups)}")
        print(
            f"retrying  : {'split only failed groups' if args.group_retry else 'disabled'}"
        )
        print(f"fallbacks : {format_retry_plan(retry_plans) if args.group_retry else 'disabled'}")
        print(f"interval  : {request.interval_ms} ms")
        if effective_samples is not None:
            print(f"samples   : {effective_samples}")
        if effective_seconds is not None:
            print(f"seconds   : {effective_seconds}")
        if effective_svg_out is not None:
            print(f"svg-out   : {effective_svg_out}")
        print(f"command   : {shlex.join(command)}")
        return 0

    renderer = DashboardRenderer(request, target, plain_output=args.plain)
    sample_stream = stream_perf_samples(
        request,
        target,
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
        retry_grouping=args.group_retry,
        on_retry=_emit_retry_notice,
    )
    csv_writer = CsvSampleWriter(args.csv_out, request, target) if args.csv_out else None
    svg_samples: list[PerfSample] = [] if effective_svg_out else []
    sample_count = 0
    interrupted = False
    started_at = time.monotonic()
    try:
        for sample in sample_stream:
            if csv_writer is not None:
                csv_writer.write(sample)
            if effective_svg_out:
                svg_samples.append(sample)
            renderer.render(sample)
            sample_count += 1
            if effective_samples is not None and sample_count >= effective_samples:
                break
            if effective_seconds is not None and time.monotonic() - started_at >= effective_seconds:
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        sample_stream.close()
        if csv_writer is not None:
            csv_writer.close()

    if effective_svg_out:
        write_svg_report(effective_svg_out, request, target, svg_samples, show_legend=args.svg_legend)
    if args.csv_out:
        print(f"csv-out   : {args.csv_out}")
    if effective_svg_out:
        print(f"svg-out   : {effective_svg_out}")
    if interrupted:
        raise KeyboardInterrupt
    return 0


def _handle_events(args: argparse.Namespace) -> int:
    return _handle_event_listing(_merge_filters(tuple(args.query), ()))


def _parse_pmu_slots_arg(raw_value: str) -> int | None:
    lowered = raw_value.strip().lower()
    if lowered == "auto":
        return None
    if not lowered.isdigit() or int(lowered) <= 0:
        raise ObservationError("pmu-slots must be 'auto' or a positive integer")
    return int(lowered)


def _resolve_limit(cli_value: int | None, parsed_value: int | None, *, label: str) -> int | None:
    value = cli_value if cli_value is not None else parsed_value
    if value is not None and value <= 0:
        raise ObservationError(f"{label} must be greater than zero")
    return value


def _merge_filters(*filter_sets: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for filter_set in filter_sets:
        for raw_value in filter_set:
            cleaned = raw_value.strip()
            if not cleaned or cleaned in seen:
                continue
            merged.append(cleaned)
            seen.add(cleaned)
    return tuple(merged)


def _resolve_svg_out(
    cli_value: str | None,
    request,
    target: TargetProcess,
    *,
    parsed,
) -> str | None:
    if cli_value:
        return cli_value
    if not parsed.wants_svg:
        return None
    return _default_svg_out(target, parsed.mentioned_events or request.events)


def _default_svg_out(target: TargetProcess, events: tuple[str, ...]) -> str:
    target_label = _slugify_path_part(target.comm) or f"pid-{target.pid}"
    selected_events = tuple(
        event for event in events if event not in {"instructions", "cycles"}
    ) or tuple(events[:2])
    event_label = "-".join(_slugify_path_part(event) for event in selected_events[:3]) or "timeline"
    return str(Path("out") / f"{target_label}-{event_label}.svg")


def _slugify_path_part(value: str) -> str:
    slug_chars: list[str] = []
    previous_dash = False
    for character in value.lower():
        if character.isascii() and (character.isalnum() or character in {"-", "_"}):
            slug_chars.append(character)
            previous_dash = False
            continue
        if not previous_dash:
            slug_chars.append("-")
            previous_dash = True
    return "".join(slug_chars).strip("-")


def _handle_event_listing(filters: tuple[str, ...], *, dry_run: bool = False) -> int:
    command = ["perf", "list", *filters]
    if dry_run:
        print("preview   : simulated dry-run only; perf itself has no --dry-run option")
        print(f"command   : {shlex.join(command)}")
        return 0

    output = _run_command(command)
    if output:
        print(output)
    return 0


def _run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise PerfStatError("perf not found in PATH", kind="tool_missing") from error

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    output = "\n".join(part for part in (stdout, stderr) if part)
    if completed.returncode != 0:
        raise PerfStatError(output or f"{' '.join(command)} exited with status {completed.returncode}", kind="process_exit")
    return output


def _emit_retry_notice(current_plan, next_plan, error: PerfStatError) -> None:
    print(current_plan, file=sys.stderr)
