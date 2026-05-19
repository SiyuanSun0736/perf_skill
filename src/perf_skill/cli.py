from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import shlex
import subprocess
import sys
import time

from perf_skill import __version__
from perf_skill.analysis import render_observation_summary, render_perf_data_summary, summarize_perf_script_output, summarize_samples, write_summary_json
from perf_skill.export import CsvSampleWriter, write_svg_report
from perf_skill.flamegraph import FLAMEGRAPH_REPO_URL, build_clone_flamegraph_command, build_flamegraph_command, build_stackcollapse_command, resolve_flamegraph_dir, write_flamegraph
from perf_skill.models import ObservationError, ObservationRequest, PerfSample, PerfStatError, TargetProcess
from perf_skill.parser import build_request, normalize_events, parse_observation_statement
from perf_skill.perf import PerfRunPlan, build_perf_annotate_command, build_perf_command, build_perf_record_command, build_perf_report_command, build_perf_script_command, build_retry_plans, detect_pmu_slot_limit, format_retry_plan, plan_event_groups, stream_perf_samples
from perf_skill.processes import resolve_target
from perf_skill.ui import DashboardRenderer


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass


ROOT_EPILOG = """Examples:
    perf-skill observe \"trace pid=4242 inst cycles\" --dry-run
    perf-skill observe \"追踪 node 的 指令 和 周期\" --plain
    perf-skill observe \"追踪 node 的 cpu-clock 和 sched:sched_switch\" --plain
    perf-skill observe \"trace pid=4242 inst cycles summary\" --summary
    perf-skill observe \"追踪 node 的 cycles 并输出 perf.data\" --seconds 10
    perf-skill observe \"追踪 node 的 cycles 并生成火焰图\" --seconds 10
    perf-skill observe \"解析 out/node_targetpid4242_cycles_data_20260519T120000.data\"
    perf-skill observe \"解析 out/node_targetpid4242_cycles_data_20260519T120000.data 并生成火焰图\"
    perf-skill observe \"trace pid=4242 inst cycles for 5 seconds\" --plain
    perf-skill observe \"我要追踪node20秒内的cycles\" --plain
    perf-skill observe \"探测20秒node的cycles并生成图像\"
    perf-skill observe \"trace comm=node branch-misses cache-misses\" --samples 10 --plain
    perf-skill observe \"trace pid=4242 inst cycles\" --csv-out out/samples.csv --svg-out out/timeline.svg
    perf-skill exercise stress-ng --load-args \"--cpu 4 --timeout 10\" --summary
    perf-skill exercise ab \"trace comm=nginx cache-misses\" --load-args \"-n 1000 -c 50 http://127.0.0.1:8080/\" --summary
    perf-skill events cache

Use 'perf-skill observe --help' for observe-specific examples and advanced grouping flags.
"""


OBSERVE_EPILOG = """Examples:
    perf-skill observe \"trace pid=4242 inst cycles\" --dry-run
    perf-skill observe \"追踪 node 的 指令 和 周期\" --plain
    perf-skill observe \"追踪 node 的 cpu-clock 和 sched:sched_switch\" --plain
    perf-skill observe \"trace pid=4242 inst cycles summary\" --summary
    perf-skill observe \"追踪 node 的 cycles 并输出 perf.data\" --seconds 10
    perf-skill observe \"追踪 node 的 cycles 并生成火焰图\" --seconds 10
    perf-skill observe \"解析 out/node_targetpid4242_cycles_data_20260519T120000.data\"
    perf-skill observe \"解析 out/node_targetpid4242_cycles_data_20260519T120000.data 并生成火焰图\"
    perf-skill observe \"trace pid=4242 inst cycles for 5 seconds\" --plain
    perf-skill observe \"我要追踪node20秒内的cycles\" --plain
    perf-skill observe \"探测20秒node的cycles并生成图像\"
    perf-skill observe \"生成10s内node的branchs的图像\"
    perf-skill observe \"trace pid=4242 branch-misses cache-misses\" --pmu-slots 2
    perf-skill observe \"trace comm=node inst cycles cache-misses\" --samples 20 --plain --csv-out out/node.csv

Grouping behavior:
    - auto: keep related counters together and split only failing groups on retry
    - auto also prefers similar event names, such as shared prefixes or suffixes
    - always: chunk the full event set by PMU slot count
    - off: disable perf groups entirely
"""


EVENTS_EPILOG = """Examples:
    perf-skill events
    perf-skill events cache
    perf-skill events branch-misses
"""


EXERCISE_EPILOG = """Examples:
    perf-skill exercise stress-ng --load-args "--cpu 4 --timeout 10" --summary
    perf-skill exercise stress-ng --load-args "--cpu 2 --timeout 5" --samples 5 --plain
    perf-skill exercise ab "trace comm=nginx cache-misses" --load-args "-n 1000 -c 50 http://127.0.0.1:8080/" --summary
    perf-skill exercise ab --comm nginx --events cycles,cache-misses --load-args "-n 500 -c 20 http://127.0.0.1:8080/"
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
        help="declarative statement such as 'trace comm=python pid=4242 inst cycles'",
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
        help="PMU slot limit for grouped hardware counters; use 'auto' for the default 4 hardware slots, while software and tracepoint events do not consume those slots",
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
        "--data-out",
        help="write perf record output to a .data file; when omitted for perf.data requests, a default out/comm_targetpid_event_data_time.data path is used",
    )
    observe_parser.add_argument(
        "--data-in",
        help="parse an existing .data file with perf script instead of live sampling",
    )
    observe_parser.add_argument(
        "--flamegraph-out",
        help="after recording or parsing perf.data, generate a FlameGraph SVG; auto-clones FlameGraph on first use",
    )
    observe_parser.add_argument(
        "--summary",
        action="store_true",
        help="print a Python-generated summary with trends, anomaly points, and derived ratios; live output also marks new anomalies, and perf.data summary aggregates top events, threads, callchains, comms, and symbols instead of dumping raw lines",
    )
    observe_parser.add_argument(
        "--summary-out",
        help="write the computed summary as JSON",
    )
    observe_parser.add_argument(
        "--report-stdio",
        action="store_true",
        help="after parsing perf.data, also run perf report --stdio as a second-hop analysis step",
    )
    observe_parser.add_argument(
        "--annotate-top",
        action="store_true",
        help="after parsing perf.data, automatically run perf annotate --stdio for the hottest parsed symbol",
    )
    observe_parser.add_argument(
        "--annotate-symbol",
        help="after parsing perf.data, run perf annotate --stdio for an explicit symbol",
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

    exercise_parser = subparsers.add_parser(
        "exercise",
        help="run a load tool and observe a target during the run",
        description="Launch stress-ng or ab, then attach perf stat either to the resolved target or to the load process itself.",
        epilog=EXERCISE_EPILOG,
        formatter_class=HelpFormatter,
    )
    exercise_parser.add_argument(
        "load_tool",
        choices=("stress-ng", "ab"),
        help="load generator to launch",
    )
    exercise_parser.add_argument(
        "statement",
        nargs="?",
        default="",
        help="optional observation statement for the target; when omitted, observe the load tool process itself",
    )
    exercise_parser.add_argument(
        "--load-args",
        default="",
        help="raw arguments passed to the load tool, for example '--cpu 4 --timeout 10' or '-n 1000 -c 50 http://127.0.0.1:8080/'",
    )
    exercise_parser.add_argument("--pid", type=int, help="explicit pid override for the observed target")
    exercise_parser.add_argument("--comm", help="explicit process comm override for the observed target")
    exercise_parser.add_argument(
        "--events",
        help="comma-separated event override such as inst,cycles,cache-misses; missing partner counters are auto-completed",
    )
    exercise_parser.add_argument(
        "--interval-ms",
        type=int,
        default=1000,
        help="perf interval in milliseconds",
    )
    exercise_parser.add_argument(
        "--history",
        type=int,
        default=30,
        help="number of recent samples to keep in the dashboard",
    )
    exercise_parser.add_argument("--samples", type=int, help="stop after collecting N samples")
    exercise_parser.add_argument("--seconds", type=int, help="stop after collecting for N seconds")
    exercise_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the load command and generated perf command without launching either of them",
    )
    exercise_parser.add_argument(
        "--plain",
        action="store_true",
        help="disable the dashboard and print one line per sample",
    )
    exercise_parser.add_argument(
        "--group-mode",
        choices=("auto", "always", "off"),
        default="auto",
        help="event grouping strategy: auto keeps related counters together and retries only failing groups, always chunks the whole set, off disables grouping",
    )
    exercise_parser.add_argument(
        "--pmu-slots",
        default="auto",
        help="PMU slot limit for grouped hardware counters; use 'auto' for the default 4 hardware slots, while software and tracepoint events do not consume those slots",
    )
    exercise_parser.add_argument("--csv-out", help="write collected samples to a CSV file as they arrive")
    exercise_parser.add_argument("--svg-out", help="write a stacked SVG time-series report after sampling finishes")
    exercise_parser.add_argument(
        "--summary",
        action="store_true",
        help="print a Python-generated post-run summary with trends, anomaly points, and derived ratios",
    )
    exercise_parser.add_argument("--summary-out", help="write the computed summary as JSON")
    exercise_parser.add_argument(
        "--svg-legend",
        dest="svg_legend",
        action="store_true",
        help="include a color legend in the SVG export",
    )
    exercise_parser.add_argument(
        "--no-svg-legend",
        dest="svg_legend",
        action="store_false",
        help="omit the color legend from the SVG export",
    )
    exercise_parser.add_argument(
        "--no-group-retry",
        dest="group_retry",
        action="store_false",
        help="disable adaptive retries that split groups further after retryable perf failures",
    )
    exercise_parser.set_defaults(svg_legend=True, group_retry=True)
    exercise_parser.set_defaults(handler=_handle_exercise)
    return parser


def _handle_observe(args: argparse.Namespace) -> int:
    if args.data_in and args.data_out:
        raise ObservationError("data-in and data-out cannot be used together")

    parsed = parse_observation_statement(args.statement)
    effective_dry_run = args.dry_run or parsed.wants_dry_run
    effective_samples = _resolve_limit(args.samples, parsed.sample_count, label="samples")
    effective_seconds = _resolve_limit(args.seconds, parsed.duration_sec, label="seconds")
    wants_summary = args.summary or parsed.wants_summary
    wants_summary_output = wants_summary or args.summary_out is not None
    effective_data_in = _resolve_data_in(args.data_in, parsed=parsed)
    wants_flamegraph = args.flamegraph_out is not None or parsed.wants_flamegraph

    if effective_data_in is not None:
        effective_flamegraph_out = _resolve_flamegraph_out(
            args.flamegraph_out,
            parsed=parsed,
            data_path=effective_data_in,
        )
        return _handle_perf_data_parse(
            effective_data_in,
            dry_run=effective_dry_run,
            wants_summary=wants_summary,
            summary_out=args.summary_out,
            report_stdio=args.report_stdio,
            annotate_top=args.annotate_top,
            annotate_symbol=args.annotate_symbol,
            flamegraph_out=effective_flamegraph_out,
        )

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
    effective_data_out = _resolve_data_out(
        args.data_out,
        request,
        target,
        parsed=parsed,
        force_record=wants_flamegraph,
    )
    effective_flamegraph_out = _resolve_flamegraph_out(
        args.flamegraph_out,
        parsed=parsed,
        data_path=effective_data_out,
    )
    retry_plans = build_retry_plans(
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
        retry_grouping=args.group_retry,
    )
    event_groups = plan_event_groups(
        request.events,
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
    )
    if effective_data_out is not None:
        command = build_perf_record_command(
            request,
            target,
            output_path=effective_data_out,
            duration_sec=effective_seconds,
            call_graph=effective_flamegraph_out is not None,
            group_mode=args.group_mode,
            pmu_slots=pmu_slots,
            groups=event_groups,
        )
    else:
        command = build_perf_command(
            request,
            target,
            group_mode=args.group_mode,
            pmu_slots=pmu_slots,
            groups=event_groups,
        )

    if effective_dry_run:
        print("preview   : simulated dry-run only; perf itself has no --dry-run option")
        print(f"statement : {request.statement or '<empty>'}")
        print(f"target    : pid={target.pid} comm={target.comm}")
        _emit_sampling_plan_preview(
            request,
            group_mode=args.group_mode,
            raw_pmu_slots=args.pmu_slots,
            resolved_pmu_slots=resolved_pmu_slots,
            event_groups=event_groups,
            group_retry=args.group_retry,
            retry_plans=retry_plans,
            effective_samples=effective_samples,
            effective_seconds=effective_seconds,
        )
        if effective_data_out is not None:
            print(f"data-out  : {effective_data_out}")
        if effective_flamegraph_out is not None:
            _emit_flamegraph_preview(effective_data_out or effective_data_in or "perf.data", effective_flamegraph_out)
        if wants_summary:
            print("summary   : enabled")
        if args.summary_out:
            print(f"summary-out: {args.summary_out}")
        if effective_svg_out is not None:
            print(f"svg-out   : {effective_svg_out}")
        print(f"command   : {shlex.join(command)}")
        return 0

    if effective_data_out is not None:
        if effective_samples is not None:
            raise ObservationError("perf.data recording does not support sample-count limits; use --seconds or stop it manually")
        if args.csv_out:
            raise ObservationError("csv-out cannot be combined with perf.data recording")
        if effective_svg_out is not None:
            raise ObservationError("svg-out cannot be combined with perf.data recording")

        data_out_path = Path(effective_data_out)
        data_out_path.parent.mkdir(parents=True, exist_ok=True)
        output = _run_command(command)
        if output:
            print(output)
        print(f"data-out  : {effective_data_out}")
        needs_script_output = wants_summary_output or args.annotate_top or effective_flamegraph_out is not None
        script_output = _run_command(build_perf_script_command(effective_data_out)) if needs_script_output else None
        summary = None
        if wants_summary_output or args.annotate_top:
            summary = _emit_perf_data_summary(
                effective_data_out,
                wants_summary=wants_summary,
                summary_out=args.summary_out,
                script_output=script_output,
            )
        if effective_flamegraph_out is not None:
            _emit_flamegraph(
                effective_data_out,
                effective_flamegraph_out,
                script_output=script_output,
            )
        if args.report_stdio or args.annotate_top or args.annotate_symbol:
            _emit_perf_data_follow_up(
                effective_data_out,
                summary=summary,
                report_stdio=args.report_stdio,
                annotate_top=args.annotate_top,
                annotate_symbol=args.annotate_symbol,
            )
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
    captured_samples: list[PerfSample] | None = [] if (effective_svg_out or wants_summary_output) else None
    sample_count = 0
    interrupted = False
    started_at = time.monotonic()
    try:
        for sample in sample_stream:
            if csv_writer is not None:
                csv_writer.write(sample)
            if captured_samples is not None:
                captured_samples.append(sample)
            renderer.render(sample)
            sample_count += 1
            if effective_samples is not None and sample_count >= effective_samples:
                break
            if effective_seconds is not None and time.monotonic() - started_at >= effective_seconds:
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        close_stream = getattr(sample_stream, "close", None)
        if callable(close_stream):
            close_stream()
        if csv_writer is not None:
            csv_writer.close()

    _emit_live_observation_outputs(
        request,
        target,
        captured_samples=captured_samples,
        wants_summary=wants_summary,
        summary_out=args.summary_out,
        csv_out=args.csv_out,
        svg_out=effective_svg_out,
        svg_legend=args.svg_legend,
    )
    if interrupted:
        raise KeyboardInterrupt
    return 0


def _handle_events(args: argparse.Namespace) -> int:
    return _handle_event_listing(_merge_filters(tuple(args.query), ()))


def _handle_exercise(args: argparse.Namespace) -> int:
    parsed = parse_observation_statement(args.statement)
    if parsed.wants_perf_data or parsed.wants_parse_data:
        raise ObservationError("exercise only supports live perf stat observation; use observe for event listing or perf.data workflows")

    effective_dry_run = args.dry_run or parsed.wants_dry_run
    effective_samples = _resolve_limit(args.samples, parsed.sample_count, label="samples")
    effective_seconds = _resolve_limit(args.seconds, parsed.duration_sec, label="seconds")
    wants_summary = args.summary or parsed.wants_summary
    wants_summary_output = wants_summary or args.summary_out is not None
    extra_events = args.events.split(",") if args.events else None
    pmu_slots = _parse_pmu_slots_arg(args.pmu_slots)
    resolved_pmu_slots = detect_pmu_slot_limit() if pmu_slots is None else pmu_slots
    load_command = _build_load_command(args.load_tool, args.load_args)

    explicit_target_requested = any(
        value is not None
        for value in (args.pid, args.comm, parsed.pid, parsed.comm)
    )
    if explicit_target_requested:
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
    else:
        request = _build_spawned_load_request(
            statement=args.statement,
            load_tool=args.load_tool,
            parsed=parsed,
            extra_events=extra_events,
            interval_ms=args.interval_ms,
            history_size=args.history,
        )
        target = TargetProcess(pid=0, comm=args.load_tool)

    retry_plans = build_retry_plans(
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
        retry_grouping=args.group_retry,
    )
    event_groups = plan_event_groups(
        request.events,
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
    )
    effective_svg_out = _resolve_svg_out(args.svg_out, request, target, parsed=parsed)

    if effective_dry_run:
        preview_target = target
        preview_request = request
        if not explicit_target_requested:
            preview_request = replace(request, pid=0, comm=args.load_tool)
        preview_command = build_perf_command(
            preview_request,
            preview_target,
            group_mode=args.group_mode,
            pmu_slots=pmu_slots,
            groups=event_groups,
        )
        if not explicit_target_requested:
            preview_command[-1] = "<load-pid>"

        print("preview   : simulated dry-run only; perf itself has no --dry-run option")
        print(f"load-tool : {args.load_tool}")
        print(f"load-cmd  : {shlex.join(load_command)}")
        print(f"statement : {args.statement or '<empty>'}")
        if explicit_target_requested:
            print(f"target    : pid={target.pid} comm={target.comm}")
        else:
            print(f"target    : spawned load process comm={args.load_tool} pid=<load-pid>")
        _emit_sampling_plan_preview(
            request,
            group_mode=args.group_mode,
            raw_pmu_slots=args.pmu_slots,
            resolved_pmu_slots=resolved_pmu_slots,
            event_groups=event_groups,
            group_retry=args.group_retry,
            retry_plans=retry_plans,
            effective_samples=effective_samples,
            effective_seconds=effective_seconds,
        )
        if wants_summary:
            print("summary   : enabled")
        if args.summary_out:
            print(f"summary-out: {args.summary_out}")
        if effective_svg_out is not None:
            print(f"svg-out   : {effective_svg_out}")
        print(f"command   : {shlex.join(preview_command)}")
        return 0

    load_process = _start_load_process(load_command, args.load_tool)
    if not explicit_target_requested:
        target = TargetProcess(pid=load_process.pid, comm=args.load_tool)
        request = replace(request, pid=target.pid, comm=target.comm)
        effective_svg_out = _resolve_svg_out(args.svg_out, request, target, parsed=parsed)

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
    captured_samples: list[PerfSample] | None = [] if (effective_svg_out or wants_summary_output) else None
    sample_count = 0
    interrupted = False
    stop_load = False
    started_at = time.monotonic()
    try:
        for sample in sample_stream:
            if csv_writer is not None:
                csv_writer.write(sample)
            if captured_samples is not None:
                captured_samples.append(sample)
            renderer.render(sample)
            sample_count += 1
            if effective_samples is not None and sample_count >= effective_samples:
                stop_load = True
                break
            if effective_seconds is not None and time.monotonic() - started_at >= effective_seconds:
                stop_load = True
                break
            if load_process.poll() is not None:
                break
    except KeyboardInterrupt:
        interrupted = True
        stop_load = True
    finally:
        close_stream = getattr(sample_stream, "close", None)
        if callable(close_stream):
            close_stream()
        if csv_writer is not None:
            csv_writer.close()

    load_stdout, load_stderr, load_returncode = _finish_load_process(
        load_process,
        stop_requested=stop_load,
    )

    _emit_live_observation_outputs(
        request,
        target,
        captured_samples=captured_samples,
        wants_summary=wants_summary,
        summary_out=args.summary_out,
        csv_out=args.csv_out,
        svg_out=effective_svg_out,
        svg_legend=args.svg_legend,
    )
    _emit_load_result(args.load_tool, load_command, load_returncode, load_stdout, load_stderr)
    if interrupted:
        raise KeyboardInterrupt
    if load_returncode != 0:
        return 2
    return 0


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


def _emit_sampling_plan_preview(
    request: ObservationRequest,
    *,
    group_mode: str,
    raw_pmu_slots: str,
    resolved_pmu_slots: int,
    event_groups: tuple[tuple[str, ...], ...],
    group_retry: bool,
    retry_plans: tuple[PerfRunPlan, ...],
    effective_samples: int | None,
    effective_seconds: int | None,
) -> None:
    print(f"events    : {', '.join(request.events)}")
    print(f"group-mode: {group_mode}")
    print(f"pmu-slots : {raw_pmu_slots} (resolved {resolved_pmu_slots})")
    print(f"groups    : {' | '.join(', '.join(group) for group in event_groups)}")
    print(
        f"retrying  : {'split only failed groups' if group_retry else 'disabled'}"
    )
    print(f"fallbacks : {format_retry_plan(retry_plans) if group_retry else 'disabled'}")
    print(f"interval  : {request.interval_ms} ms")
    if effective_samples is not None:
        print(f"samples   : {effective_samples}")
    if effective_seconds is not None:
        print(f"seconds   : {effective_seconds}")


def _emit_live_observation_outputs(
    request: ObservationRequest,
    target: TargetProcess,
    *,
    captured_samples: list[PerfSample] | None,
    wants_summary: bool,
    summary_out: str | None,
    csv_out: str | None,
    svg_out: str | None,
    svg_legend: bool,
) -> None:
    wants_summary_output = wants_summary or summary_out is not None
    samples = captured_samples or []

    if svg_out:
        write_svg_report(
            svg_out,
            request,
            target,
            samples,
            show_legend=svg_legend,
        )
    if wants_summary_output:
        summary = summarize_samples(request, target, samples)
        if wants_summary:
            print(render_observation_summary(summary))
        if summary_out:
            write_summary_json(summary_out, summary)
            print(f"summary-out: {summary_out}")
    if csv_out:
        print(f"csv-out   : {csv_out}")
    if svg_out:
        print(f"svg-out   : {svg_out}")


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


def _resolve_data_out(
    cli_value: str | None,
    request,
    target: TargetProcess,
    *,
    parsed,
    force_record: bool = False,
) -> str | None:
    if cli_value:
        return cli_value
    if not parsed.wants_perf_data and not force_record:
        return None
    if parsed.data_path and parsed.data_path.lower() != "perf.data":
        return parsed.data_path
    return _default_data_out(target, parsed.mentioned_events or request.events)


def _resolve_flamegraph_out(
    cli_value: str | None,
    *,
    parsed,
    data_path: str | None,
) -> str | None:
    if cli_value:
        return cli_value
    if not parsed.wants_flamegraph or data_path is None:
        return None
    return _default_flamegraph_out(data_path)


def _resolve_data_in(
    cli_value: str | None,
    *,
    parsed,
) -> str | None:
    if cli_value:
        return _require_existing_data_path(cli_value)
    if parsed.data_path and parsed.wants_parse_data and parsed.data_path.lower() != "perf.data":
        return _require_existing_data_path(parsed.data_path)
    if not parsed.wants_parse_data:
        return None

    default_path = Path("perf.data")
    if default_path.exists():
        return str(default_path)

    latest_data = _find_latest_perf_data()
    if latest_data is None:
        raise ObservationError(
            "missing perf.data file: specify --data-in, mention a .data path, or record perf.data first"
        )
    return str(latest_data)


def _handle_perf_data_parse(
    data_path: str,
    *,
    dry_run: bool,
    wants_summary: bool,
    summary_out: str | None,
    report_stdio: bool,
    annotate_top: bool,
    annotate_symbol: str | None,
    flamegraph_out: str | None,
) -> int:
    command = build_perf_script_command(data_path)
    if dry_run:
        print("preview   : simulated dry-run only; perf itself has no --dry-run option")
        print(f"data-in   : {data_path}")
        if wants_summary:
            print("summary   : enabled")
        if summary_out:
            print(f"summary-out: {summary_out}")
        if report_stdio:
            print("report    : perf report --stdio")
        if annotate_top:
            print("annotate  : hottest parsed symbol")
        if annotate_symbol:
            print(f"annotate  : {annotate_symbol}")
        if flamegraph_out is not None:
            _emit_flamegraph_preview(data_path, flamegraph_out)
        print(f"command   : {shlex.join(command)}")
        return 0

    needs_script_output = (
        wants_summary
        or summary_out
        or annotate_top
        or flamegraph_out is not None
        or not (report_stdio or annotate_symbol)
    )
    script_output = _run_command(command) if needs_script_output else None
    summary = None
    if needs_script_output and (wants_summary or summary_out or annotate_top):
        summary = _emit_perf_data_summary(
            data_path,
            wants_summary=wants_summary,
            summary_out=summary_out,
            script_output=script_output,
        )
    if flamegraph_out is not None:
        _emit_flamegraph(
            data_path,
            flamegraph_out,
            script_output=script_output,
        )
    if report_stdio or annotate_top or annotate_symbol:
        _emit_perf_data_follow_up(
            data_path,
            summary=summary,
            report_stdio=report_stdio,
            annotate_top=annotate_top,
            annotate_symbol=annotate_symbol,
        )
        return 0
    if script_output and flamegraph_out is None:
        print(script_output)
    return 0


def _emit_perf_data_summary(
    data_path: str,
    *,
    wants_summary: bool,
    summary_out: str | None,
    script_output: str | None = None,
) -> object:
    output = script_output if script_output is not None else _run_command(build_perf_script_command(data_path))
    summary = summarize_perf_script_output(data_path, output)
    if wants_summary:
        print(render_perf_data_summary(summary))
    if summary_out:
        write_summary_json(summary_out, summary)
        print(f"summary-out: {summary_out}")
    return summary


def _emit_perf_data_follow_up(
    data_path: str,
    *,
    summary,
    report_stdio: bool,
    annotate_top: bool,
    annotate_symbol: str | None,
) -> None:
    if report_stdio:
        print("report    : perf report --stdio")
        output = _run_command(build_perf_report_command(data_path))
        if output:
            print(output)

    resolved_symbol = annotate_symbol
    if resolved_symbol is None and annotate_top:
        resolved_symbol = _resolve_top_hotspot_symbol(summary)
        if resolved_symbol is None:
            print("annotate  : skipped; no hotspot symbol was parsed")
            return

    if resolved_symbol is None:
        return

    print(f"annotate  : {resolved_symbol}")
    output = _run_command(build_perf_annotate_command(data_path, symbol=resolved_symbol))
    if output:
        print(output)


def _emit_flamegraph_preview(data_path: str, output_path: str) -> None:
    repo_dir = resolve_flamegraph_dir()
    title = _default_flamegraph_title(data_path)
    stackcollapse_command = build_stackcollapse_command(repo_dir)
    flamegraph_command = build_flamegraph_command(repo_dir, title=title)
    clone_command = build_clone_flamegraph_command(repo_dir)
    print(f"flamegraph: {output_path}")
    print(f"fg-repo   : {FLAMEGRAPH_REPO_URL}")
    print(f"fg-dir    : {repo_dir}")
    print(f"bootstrap : {shlex.join(clone_command)}")
    print(
        "pipeline  : "
        f"{shlex.join(build_perf_script_command(data_path))}"
        f" | {shlex.join(stackcollapse_command)}"
        f" | {shlex.join(flamegraph_command)}"
        f" > {shlex.quote(output_path)}"
    )


def _emit_flamegraph(
    data_path: str,
    output_path: str,
    *,
    script_output: str | None = None,
) -> None:
    output = script_output if script_output is not None else _run_command(build_perf_script_command(data_path))
    write_flamegraph(output, output_path, title=_default_flamegraph_title(data_path))
    print(f"flamegraph: {output_path}")


def _default_svg_out(target: TargetProcess, events: tuple[str, ...]) -> str:
    target_label = _slugify_path_part(target.comm) or f"pid-{target.pid}"
    selected_events = tuple(
        event for event in events if event not in {"instructions", "cycles"}
    ) or tuple(events[:2])
    event_label = "-".join(_slugify_path_part(event) for event in selected_events[:3]) or "timeline"
    return str(Path("out") / f"{target_label}-{event_label}.svg")


def _default_data_out(target: TargetProcess, events: tuple[str, ...]) -> str:
    target_label = _slugify_path_part(target.comm) or f"pid-{target.pid}"
    selected_events = tuple(
        event for event in events if event not in {"instructions", "cycles"}
    ) or tuple(events[:2])
    event_label = "-".join(_slugify_path_part(event) for event in selected_events[:3]) or "timeline"
    return str(
        Path("out")
        / f"{target_label}_targetpid{target.pid}_{event_label}_data_{_current_data_timestamp()}.data"
    )


def _default_flamegraph_out(data_path: str) -> str:
    path = Path(data_path)
    return str(path.with_name(f"{path.stem}-flamegraph.svg"))


def _default_flamegraph_title(data_path: str) -> str:
    return f"perf.data: {Path(data_path).name}"


def _current_data_timestamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


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


def _require_existing_data_path(raw_path: str) -> str:
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        raise ObservationError(f"perf.data file not found: {raw_path}")
    return str(path)


def _find_latest_perf_data() -> Path | None:
    candidates: list[Path] = []
    for path in Path(".").glob("*.data"):
        if path.is_file():
            candidates.append(path)
    out_dir = Path("out")
    if out_dir.exists():
        for path in out_dir.rglob("*.data"):
            if path.is_file():
                candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


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


def _resolve_top_hotspot_symbol(summary) -> str | None:
    if summary is None:
        return None
    hotspots = getattr(summary, "hotspots", ())
    if not hotspots:
        return None
    hottest_name = hotspots[0][0]
    if " [" in hottest_name:
        return hottest_name.rsplit(" [", 1)[0]
    return hottest_name


def _build_spawned_load_request(
    *,
    statement: str,
    load_tool: str,
    parsed,
    extra_events: list[str] | None,
    interval_ms: int,
    history_size: int,
) -> ObservationRequest:
    if interval_ms <= 0:
        raise ObservationError("interval-ms must be greater than zero")
    if history_size <= 0:
        raise ObservationError("history must be greater than zero")

    resolved_events = parsed.events or normalize_events(())
    if extra_events:
        resolved_events = normalize_events(tuple(extra_events))

    return ObservationRequest(
        statement=statement or f"exercise {load_tool}",
        pid=None,
        comm=None,
        events=resolved_events,
        interval_ms=interval_ms,
        history_size=history_size,
    )


def _build_load_command(load_tool: str, raw_args: str) -> list[str]:
    command = [load_tool]
    if raw_args.strip():
        command.extend(shlex.split(raw_args))
    return command


def _start_load_process(load_command: list[str], load_tool: str) -> subprocess.Popen[str]:
    try:
        return subprocess.Popen(
            load_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise ObservationError(f"load tool not found in PATH: {load_tool}") from error


def _finish_load_process(
    process: subprocess.Popen[str],
    *,
    stop_requested: bool,
) -> tuple[str, str, int]:
    if stop_requested and process.poll() is None:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()

    return stdout.strip(), stderr.strip(), process.returncode or 0


def _emit_load_result(
    load_tool: str,
    load_command: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
) -> None:
    print(f"load-tool : {load_tool}")
    print(f"load-cmd  : {shlex.join(load_command)}")
    print(f"load-exit : {returncode}")
    if stdout:
        print("load-stdout:")
        print(stdout)
    if stderr:
        print("load-stderr:")
        print(stderr)


def _emit_retry_notice(message: str) -> None:
    print(message, file=sys.stderr)
