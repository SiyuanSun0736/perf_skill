from __future__ import annotations

import subprocess
from dataclasses import dataclass
from collections.abc import Iterable, Iterator

from perf_skill.models import PerfMeasurement, PerfSample, PerfStatError, ObservationRequest, TargetProcess
from perf_skill.parser import normalize_event_name

NOT_A_NUMBER = {
    "",
    "<not counted>",
    "<not supported>",
    "not counted",
    "not supported",
}


@dataclass(frozen=True)
class PerfStatus:
    timestamp_sec: float
    event: str
    status: str


GROUP_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("instructions", "cycles"),
    ("branches", "branch-misses"),
    ("cache-references", "cache-misses"),
)
GROUP_MODES = {"auto", "always", "off"}
DEFAULT_GROUP_SIZE = 4


def build_perf_command(
    request: ObservationRequest,
    target: TargetProcess,
    *,
    group_mode: str = "auto",
) -> list[str]:
    return [
        "perf",
        "stat",
        "--interval-print",
        str(request.interval_ms),
        "--no-big-num",
        "-x",
        ",",
        "-e",
        build_event_expression(request.events, group_mode=group_mode),
        "-p",
        str(target.pid),
    ]


def plan_event_groups(
    events: Iterable[str],
    *,
    group_mode: str = "auto",
    max_group_size: int = DEFAULT_GROUP_SIZE,
) -> tuple[tuple[str, ...], ...]:
    ordered_events = tuple(dict.fromkeys(events))
    _validate_group_mode(group_mode)
    if max_group_size <= 0:
        raise PerfStatError("group size must be greater than zero")

    if not ordered_events:
        return ()
    if group_mode == "off":
        return tuple((event,) for event in ordered_events)
    if group_mode == "always":
        return _chunk_groups(ordered_events, max_group_size=max_group_size)
    return _plan_auto_groups(ordered_events, max_group_size=max_group_size)


def build_event_expression(
    events: Iterable[str],
    *,
    group_mode: str = "auto",
    max_group_size: int = DEFAULT_GROUP_SIZE,
) -> str:
    groups = plan_event_groups(events, group_mode=group_mode, max_group_size=max_group_size)
    rendered_groups: list[str] = []
    for group in groups:
        if len(group) == 1:
            rendered_groups.append(group[0])
        else:
            rendered_groups.append("{" + ",".join(group) + "}")
    return ",".join(rendered_groups)


def stream_perf_samples(
    request: ObservationRequest,
    target: TargetProcess,
    *,
    group_mode: str = "auto",
) -> Iterator[PerfSample]:
    command = build_perf_command(request, target, group_mode=group_mode)
    interval_tolerance = max(request.interval_ms / 1000.0 / 5.0, 0.05)

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as error:
        raise PerfStatError("perf not found in PATH") from error

    pending_timestamp: float | None = None
    pending_values: dict[str, float] = {}
    diagnostics: list[str] = []
    unsupported_events: dict[str, str] = {}

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue

            measurement = parse_perf_csv_line(line, request.events)
            if measurement is not None:
                if pending_timestamp is None:
                    pending_timestamp = measurement.timestamp_sec
                elif abs(measurement.timestamp_sec - pending_timestamp) > interval_tolerance:
                    yield _build_sample(pending_timestamp, pending_values)
                    pending_timestamp = measurement.timestamp_sec
                    pending_values = {}

                pending_values[measurement.event] = measurement.value
                continue

            status = parse_perf_status_line(line, request.events)
            if status is None:
                diagnostics.append(line)
                continue

            unsupported_events[status.event] = status.status
            diagnostics.append(line)
            if pending_timestamp is None:
                pending_timestamp = status.timestamp_sec
            if _all_events_unsupported(request.events, unsupported_events):
                raise PerfStatError(_format_unsupported_events(unsupported_events, diagnostics))

        return_code = process.wait()
        if pending_timestamp is not None and pending_values:
            yield _build_sample(pending_timestamp, pending_values)

        if return_code not in (0, None):
            if diagnostics:
                raise PerfStatError(_format_diagnostics(diagnostics))
            raise PerfStatError(f"perf exited with status {return_code}")
    finally:
        if process.poll() is None:
            process.terminate()


def parse_perf_csv_line(line: str, known_events: Iterable[str]) -> PerfMeasurement | None:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 4:
        return None

    timestamp = _parse_float(parts[0])
    if timestamp is None:
        return None

    value = _parse_float(parts[1])
    if value is None:
        return None

    known = {event for event in known_events}
    for part in parts[2:]:
        event_name = normalize_event_name(part)
        if event_name is not None and event_name in known:
            return PerfMeasurement(timestamp_sec=timestamp, event=event_name, value=value)
    return None


def parse_perf_status_line(line: str, known_events: Iterable[str]) -> PerfStatus | None:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 4:
        return None

    timestamp = _parse_float(parts[0])
    if timestamp is None:
        return None

    status = parts[1].lower()
    if status not in {"<not counted>", "<not supported>", "not counted", "not supported"}:
        return None

    known = {event for event in known_events}
    for part in parts[2:]:
        event_name = normalize_event_name(part)
        if event_name is not None and event_name in known:
            return PerfStatus(timestamp_sec=timestamp, event=event_name, status=status.strip("<>"))
    return None


def _build_sample(timestamp_sec: float, values: dict[str, float]) -> PerfSample:
    instructions = values.get("instructions")
    cycles = values.get("cycles")
    ipc = None
    if instructions is not None and cycles not in (None, 0.0):
        ipc = instructions / cycles
    return PerfSample(timestamp_sec=timestamp_sec, values=dict(values), ipc=ipc)


def _parse_float(raw_value: str) -> float | None:
    cleaned = raw_value.strip()
    if cleaned.lower() in NOT_A_NUMBER:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _format_diagnostics(diagnostics: list[str]) -> str:
    collapsed: list[str] = []
    for line in diagnostics:
        if collapsed and collapsed[-1] == line:
            continue
        collapsed.append(line)
    return "\n".join(collapsed[-5:])


def _all_events_unsupported(events: Iterable[str], unsupported_events: dict[str, str]) -> bool:
    required = {event for event in events}
    return required.issubset(unsupported_events)


def _format_unsupported_events(unsupported_events: dict[str, str], diagnostics: list[str]) -> str:
    rendered = ", ".join(
        f"{event}={unsupported_events[event]}" for event in sorted(unsupported_events)
    )
    suffix = _format_diagnostics(diagnostics)
    return (
        "perf reported unsupported or uncounted hardware events for this target: "
        f"{rendered}\n{suffix}\n"
        "This often means the current kernel, VM, or permissions model does not expose PMU counters."
    )


def _validate_group_mode(group_mode: str) -> None:
    if group_mode not in GROUP_MODES:
        supported = ", ".join(sorted(GROUP_MODES))
        raise PerfStatError(f"unsupported group mode: {group_mode}; expected one of {supported}")


def _chunk_groups(
    ordered_events: tuple[str, ...],
    *,
    max_group_size: int,
) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    for index in range(0, len(ordered_events), max_group_size):
        groups.append(ordered_events[index:index + max_group_size])
    return tuple(groups)


def _plan_auto_groups(
    ordered_events: tuple[str, ...],
    *,
    max_group_size: int,
) -> tuple[tuple[str, ...], ...]:
    remaining = list(ordered_events)
    groups: list[list[str]] = []

    for family in GROUP_FAMILIES:
        family_group = [event for event in family if event in remaining]
        if not family_group:
            continue
        groups.append(family_group)
        for event in family_group:
            remaining.remove(event)

    for event in remaining:
        for group in groups:
            if len(group) < max_group_size:
                group.append(event)
                break
        else:
            groups.append([event])

    merged_groups = _merge_singleton_groups(groups, max_group_size=max_group_size)
    return tuple(tuple(group) for group in merged_groups)


def _merge_singleton_groups(
    groups: list[list[str]],
    *,
    max_group_size: int,
) -> list[list[str]]:
    if not groups:
        return []

    merged_groups: list[list[str]] = [list(groups[0])]
    for group in groups[1:]:
        if len(group) == 1:
            for target_group in merged_groups:
                if len(target_group) < max_group_size:
                    target_group.extend(group)
                    break
            else:
                merged_groups.append(list(group))
            continue
        merged_groups.append(list(group))
    return merged_groups
