from __future__ import annotations

import argparse
import shlex
import sys

from perf_skill.export import CsvSampleWriter, write_svg_report
from perf_skill.models import ObservationError, PerfSample, PerfStatError
from perf_skill.parser import build_request
from perf_skill.perf import build_perf_command, detect_pmu_slot_limit, plan_event_groups, stream_perf_samples
from perf_skill.processes import resolve_target
from perf_skill.ui import DashboardRenderer


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
    )
    subparsers = parser.add_subparsers(dest="command")

    observe_parser = subparsers.add_parser(
        "observe",
        help="parse a statement, resolve a target, and stream perf counters",
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
        help="comma-separated event override such as inst,cycles,cache-misses",
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
        "--dry-run",
        action="store_true",
        help="show the resolved request and perf command without running perf",
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
        help="event grouping strategy: auto groups related counters, always chunks all counters, off disables grouping",
    )
    observe_parser.add_argument(
        "--pmu-slots",
        default="auto",
        help="PMU slot limit for group splitting; use 'auto' to read local hints and vendor heuristics",
    )
    observe_parser.add_argument(
        "--csv-out",
        help="write collected samples to a CSV file",
    )
    observe_parser.add_argument(
        "--svg-out",
        help="write a stacked SVG time-series report after sampling finishes",
    )
    observe_parser.set_defaults(handler=_handle_observe)
    return parser


def _handle_observe(args: argparse.Namespace) -> int:
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
    )
    target = resolve_target(request)
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

    if args.dry_run:
        print(f"statement : {request.statement or '<empty>'}")
        print(f"target    : pid={target.pid} comm={target.comm}")
        print(f"events    : {', '.join(request.events)}")
        print(f"group-mode: {args.group_mode}")
        print(f"pmu-slots : {args.pmu_slots} (resolved {resolved_pmu_slots})")
        print(f"groups    : {' | '.join(', '.join(group) for group in event_groups)}")
        print(f"interval  : {request.interval_ms} ms")
        print(f"command   : {shlex.join(command)}")
        return 0

    renderer = DashboardRenderer(request, target, plain_output=args.plain)
    sample_stream = stream_perf_samples(
        request,
        target,
        group_mode=args.group_mode,
        pmu_slots=pmu_slots,
    )
    csv_writer = CsvSampleWriter(args.csv_out, request, target) if args.csv_out else None
    svg_samples: list[PerfSample] = [] if args.svg_out else []
    sample_count = 0
    interrupted = False
    try:
        for sample in sample_stream:
            if csv_writer is not None:
                csv_writer.write(sample)
            if args.svg_out:
                svg_samples.append(sample)
            renderer.render(sample)
            sample_count += 1
            if args.samples is not None and sample_count >= args.samples:
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        sample_stream.close()
        if csv_writer is not None:
            csv_writer.close()

    if args.svg_out:
        write_svg_report(args.svg_out, request, target, svg_samples)
    if args.csv_out:
        print(f"csv-out   : {args.csv_out}")
    if args.svg_out:
        print(f"svg-out   : {args.svg_out}")
    if interrupted:
        raise KeyboardInterrupt
    return 0


def _parse_pmu_slots_arg(raw_value: str) -> int | None:
    lowered = raw_value.strip().lower()
    if lowered == "auto":
        return None
    if not lowered.isdigit() or int(lowered) <= 0:
        raise ObservationError("pmu-slots must be 'auto' or a positive integer")
    return int(lowered)
