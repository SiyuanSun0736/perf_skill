from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
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


@dataclass(frozen=True)
class PerfRunPlan:
    group_mode: str
    pmu_slots: int


GROUP_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("instructions", "cycles"),
    ("branches", "branch-misses"),
    ("cache-references", "cache-misses"),
)
GROUP_MODES = {"auto", "always", "off"}
DEFAULT_GROUP_SIZE = 4
AMD_DEFAULT_GROUP_SIZE = 6
PMU_COUNTER_HINT_PATHS = (
    Path("/sys/bus/event_source/devices/cpu/caps/num_counters"),
    Path("/sys/bus/event_source/devices/cpu/num_counters"),
    Path("/sys/bus/event_source/devices/cpu/caps/max_hw_counters"),
    Path("/sys/devices/cpu/caps/num_counters"),
)
RETRYABLE_DIAGNOSTIC_KEYWORDS = (
    "not counted",
    "not supported",
    "too many events",
    "counter",
    "group",
    "schedule",
    "multiplex",
)


def build_perf_command(
    request: ObservationRequest,
    target: TargetProcess,
    *,
    group_mode: str = "auto",
    pmu_slots: int | None = None,
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
        build_event_expression(request.events, group_mode=group_mode, pmu_slots=pmu_slots),
        "-p",
        str(target.pid),
    ]


def plan_event_groups(
    events: Iterable[str],
    *,
    group_mode: str = "auto",
    pmu_slots: int | None = None,
) -> tuple[tuple[str, ...], ...]:
    ordered_events = tuple(dict.fromkeys(events))
    _validate_group_mode(group_mode)
    max_group_size = resolve_pmu_slot_limit(pmu_slots)

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
    pmu_slots: int | None = None,
) -> str:
    groups = plan_event_groups(events, group_mode=group_mode, pmu_slots=pmu_slots)
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
    pmu_slots: int | None = None,
    retry_grouping: bool = True,
    on_retry: Callable[[PerfRunPlan, PerfRunPlan, PerfStatError], None] | None = None,
) -> Iterator[PerfSample]:
    plans = build_retry_plans(
        group_mode=group_mode,
        pmu_slots=pmu_slots,
        retry_grouping=retry_grouping,
    )

    for index, plan in enumerate(plans):
        emitted_samples = False
        try:
            for sample in _stream_perf_attempt(
                request,
                target,
                group_mode=plan.group_mode,
                pmu_slots=plan.pmu_slots,
            ):
                emitted_samples = True
                yield sample
            return
        except PerfStatError as error:
            is_last_plan = index == len(plans) - 1
            if emitted_samples or is_last_plan or not _is_retryable_grouping_error(error):
                raise
            next_plan = plans[index + 1]
            if on_retry is not None:
                on_retry(plan, next_plan, error)


def _stream_perf_attempt(
    request: ObservationRequest,
    target: TargetProcess,
    *,
    group_mode: str,
    pmu_slots: int | None,
) -> Iterator[PerfSample]:
    command = build_perf_command(request, target, group_mode=group_mode, pmu_slots=pmu_slots)
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
        raise PerfStatError("perf not found in PATH", kind="tool_missing") from error

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
                raise PerfStatError(
                    _format_unsupported_events(unsupported_events, diagnostics),
                    kind="unsupported_events",
                    diagnostics=tuple(diagnostics),
                    unsupported_events=unsupported_events,
                )

        return_code = process.wait()
        if pending_timestamp is not None and pending_values:
            yield _build_sample(pending_timestamp, pending_values)

        if return_code not in (0, None):
            if diagnostics:
                raise PerfStatError(
                    _format_diagnostics(diagnostics),
                    kind="process_exit",
                    diagnostics=tuple(diagnostics),
                )
            raise PerfStatError(f"perf exited with status {return_code}", kind="process_exit")
    finally:
        if process.poll() is None:
            process.terminate()


def build_retry_plans(
    *,
    group_mode: str,
    pmu_slots: int | None,
    retry_grouping: bool,
) -> tuple[PerfRunPlan, ...]:
    resolved_slots = resolve_pmu_slot_limit(pmu_slots)
    plans = [PerfRunPlan(group_mode=group_mode, pmu_slots=resolved_slots)]
    if not retry_grouping or group_mode == "off":
        return tuple(plans)

    current_slots = resolved_slots
    while current_slots > 1:
        next_slots = _next_lower_slot_limit(current_slots)
        if next_slots is None:
            break
        plans.append(PerfRunPlan(group_mode=group_mode, pmu_slots=next_slots))
        current_slots = next_slots

    if plans[-1].group_mode != "off":
        plans.append(PerfRunPlan(group_mode="off", pmu_slots=1))
    return _dedupe_retry_plans(tuple(plans))


def format_retry_plan(plans: Iterable[PerfRunPlan]) -> str:
    return " -> ".join(f"{plan.group_mode}/{plan.pmu_slots}" for plan in plans)


def format_retry_notice(
    current_plan: PerfRunPlan,
    next_plan: PerfRunPlan,
    error: PerfStatError,
) -> str:
    reason = _summarize_retry_reason(error)
    return (
        f"retry     : {reason}; "
        f"retrying with group-mode={next_plan.group_mode} pmu-slots={next_plan.pmu_slots} "
        f"after {current_plan.group_mode}/{current_plan.pmu_slots}"
    )


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


@lru_cache(maxsize=1)
def detect_pmu_slot_limit() -> int:
    for path in PMU_COUNTER_HINT_PATHS:
        value = _read_positive_int(path)
        if value is not None:
            return value

    cpuinfo = _read_cpuinfo_fields()
    vendor = cpuinfo.get("vendor_id", "")
    family = _try_parse_int(cpuinfo.get("cpu family"))
    if vendor == "AuthenticAMD" and family is not None and family >= 23:
        return AMD_DEFAULT_GROUP_SIZE
    if vendor == "GenuineIntel":
        return DEFAULT_GROUP_SIZE
    return DEFAULT_GROUP_SIZE


def resolve_pmu_slot_limit(pmu_slots: int | None) -> int:
    resolved = detect_pmu_slot_limit() if pmu_slots is None else pmu_slots
    if resolved <= 0:
        raise PerfStatError("pmu slot limit must be greater than zero")
    return resolved


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

    split_groups = _split_oversized_groups(groups, max_group_size=max_group_size)
    merged_groups = _merge_singleton_groups(split_groups, max_group_size=max_group_size)
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


def _split_oversized_groups(
    groups: list[list[str]],
    *,
    max_group_size: int,
) -> list[list[str]]:
    split_groups: list[list[str]] = []
    for group in groups:
        if len(group) <= max_group_size:
            split_groups.append(list(group))
            continue
        for index in range(0, len(group), max_group_size):
            split_groups.append(group[index:index + max_group_size])
    return split_groups


def _read_positive_int(path: Path) -> int | None:
    try:
        raw_value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    parsed = _try_parse_int(raw_value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _read_cpuinfo_fields(path: Path = Path("/proc/cpuinfo")) -> dict[str, str]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    first_block = contents.strip().split("\n\n", maxsplit=1)[0]
    fields: dict[str, str] = {}
    for line in first_block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        fields[key.strip()] = value.strip()
    return fields


def _try_parse_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def _next_lower_slot_limit(current_slots: int) -> int | None:
    if current_slots <= 1:
        return None
    next_slots = max(1, current_slots // 2)
    if next_slots == current_slots:
        next_slots = current_slots - 1
    return next_slots


def _dedupe_retry_plans(plans: tuple[PerfRunPlan, ...]) -> tuple[PerfRunPlan, ...]:
    deduped: list[PerfRunPlan] = []
    seen: set[tuple[str, int]] = set()
    for plan in plans:
        key = (plan.group_mode, plan.pmu_slots)
        if key in seen:
            continue
        deduped.append(plan)
        seen.add(key)
    return tuple(deduped)


def _is_retryable_grouping_error(error: PerfStatError) -> bool:
    if error.kind == "unsupported_events":
        return True
    text = "\n".join(error.diagnostics).lower() or str(error).lower()
    return any(keyword in text for keyword in RETRYABLE_DIAGNOSTIC_KEYWORDS)


def _summarize_retry_reason(error: PerfStatError) -> str:
    if error.kind == "unsupported_events":
        return "perf reported uncounted or unsupported grouped events"
    diagnostic_lines = list(error.diagnostics)
    if diagnostic_lines:
        return diagnostic_lines[-1]
    return str(error)
