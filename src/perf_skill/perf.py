from __future__ import annotations

import queue
import threading
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


@dataclass(frozen=True)
class PerfGroupTask:
    worker_id: int
    group: tuple[str, ...]
    pmu_slots: int


@dataclass(frozen=True)
class _GroupSampleMessage:
    task: PerfGroupTask
    sample: PerfSample


@dataclass(frozen=True)
class _GroupRetryMessage:
    task: PerfGroupTask
    child_groups: tuple[tuple[str, ...], ...]
    next_pmu_slots: int
    error: PerfStatError


@dataclass(frozen=True)
class _GroupDoneMessage:
    task: PerfGroupTask


@dataclass(frozen=True)
class _GroupErrorMessage:
    task: PerfGroupTask
    error: PerfStatError


@dataclass
class _PendingSampleBucket:
    timestamp_sec: float
    values: dict[str, float]


GROUP_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("instructions", "cycles"),
    ("branches", "branch-misses"),
    ("cache-references", "cache-misses"),
)
GROUP_MODES = {"auto", "always", "off"}
DEFAULT_GROUP_SIZE = 4
SOFTWARE_EVENTS = {
    "alignment-faults",
    "bpf-output",
    "context-switches",
    "cpu-clock",
    "cpu-migrations",
    "dummy",
    "emulation-faults",
    "major-faults",
    "minor-faults",
    "page-faults",
    "task-clock",
}
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
    groups: tuple[tuple[str, ...], ...] | None = None,
) -> list[str]:
    resolved_groups = groups or plan_event_groups(
        request.events,
        group_mode=group_mode,
        pmu_slots=pmu_slots,
    )
    return [
        "perf",
        "stat",
        "--interval-print",
        str(request.interval_ms),
        "--no-big-num",
        "-x",
        ",",
        "-e",
        build_group_expression(resolved_groups),
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
    return build_group_expression(groups)


def build_group_expression(groups: Iterable[tuple[str, ...]]) -> str:
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
    on_retry: Callable[[str], None] | None = None,
) -> Iterator[PerfSample]:
    resolved_pmu_slots = resolve_pmu_slot_limit(pmu_slots)
    initial_groups = plan_event_groups(
        request.events,
        group_mode=group_mode,
        pmu_slots=resolved_pmu_slots,
    )
    merge_tolerance = max(request.interval_ms / 1000.0 / 4.0, 0.1)
    message_queue: queue.Queue[
        _GroupSampleMessage | _GroupRetryMessage | _GroupDoneMessage | _GroupErrorMessage
    ] = queue.Queue()
    stop_event = threading.Event()
    threads: dict[int, threading.Thread] = {}
    pending_buckets: list[_PendingSampleBucket] = []
    active_workers = 0
    next_worker_id = 0
    fatal_error: PerfStatError | None = None

    def spawn_group(group: tuple[str, ...], group_pmu_slots: int) -> None:
        nonlocal active_workers, next_worker_id
        task = PerfGroupTask(
            worker_id=next_worker_id,
            group=group,
            pmu_slots=group_pmu_slots,
        )
        next_worker_id += 1
        thread = threading.Thread(
            target=_run_group_task,
            args=(
                request,
                target,
                task,
                message_queue,
                stop_event,
                retry_grouping,
            ),
            daemon=True,
        )
        threads[task.worker_id] = thread
        active_workers += 1
        thread.start()

    for group in initial_groups:
        spawn_group(group, resolved_pmu_slots)

    try:
        while active_workers > 0:
            message = message_queue.get()
            if isinstance(message, _GroupSampleMessage):
                _add_partial_sample(pending_buckets, message.sample, tolerance=merge_tolerance)
                for ready_sample in _pop_ready_samples(
                    pending_buckets,
                    newest_timestamp=message.sample.timestamp_sec,
                    tolerance=merge_tolerance,
                ):
                    yield ready_sample
                continue

            if isinstance(message, _GroupRetryMessage):
                active_workers -= 1
                if on_retry is not None:
                    on_retry(format_group_retry_notice(message.task, message.child_groups, message.error))
                for child_group in message.child_groups:
                    spawn_group(child_group, message.next_pmu_slots)
                continue

            if isinstance(message, _GroupDoneMessage):
                active_workers -= 1
                continue

            if isinstance(message, _GroupErrorMessage):
                active_workers -= 1
                fatal_error = message.error
                stop_event.set()
                break

        for ready_sample in _drain_pending_samples(pending_buckets):
            yield ready_sample

        if fatal_error is not None:
            raise fatal_error
    finally:
        stop_event.set()
        join_timeout = max(request.interval_ms / 1000.0, 0.2)
        for thread in threads.values():
            thread.join(timeout=join_timeout)


def _run_group_task(
    request: ObservationRequest,
    target: TargetProcess,
    task: PerfGroupTask,
    message_queue: queue.Queue[
        _GroupSampleMessage | _GroupRetryMessage | _GroupDoneMessage | _GroupErrorMessage
    ],
    stop_event: threading.Event,
    retry_grouping: bool,
) -> None:
    if stop_event.is_set():
        return

    emitted_samples = False
    group_request = _build_group_request(request, task.group)
    try:
        for sample in _stream_perf_attempt(
            group_request,
            target,
            groups=(task.group,),
            stop_event=stop_event,
        ):
            if stop_event.is_set():
                return
            emitted_samples = True
            message_queue.put(_GroupSampleMessage(task=task, sample=sample))
    except PerfStatError as error:
        if stop_event.is_set():
            return
        retry_plan = _plan_group_retry(task, error, retry_grouping=retry_grouping)
        if not emitted_samples and retry_plan is not None:
            child_groups, next_pmu_slots = retry_plan
            message_queue.put(
                _GroupRetryMessage(
                    task=task,
                    child_groups=child_groups,
                    next_pmu_slots=next_pmu_slots,
                    error=error,
                )
            )
            return
        message_queue.put(_GroupErrorMessage(task=task, error=error))
        return

    if not stop_event.is_set():
        message_queue.put(_GroupDoneMessage(task=task))


def _stream_perf_attempt(
    request: ObservationRequest,
    target: TargetProcess,
    *,
    groups: tuple[tuple[str, ...], ...] | None = None,
    stop_event: threading.Event | None = None,
) -> Iterator[PerfSample]:
    command = build_perf_command(request, target, groups=groups)
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
            if stop_event is not None and stop_event.is_set():
                break
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
        if stop_event is not None and stop_event.is_set():
            return
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


def format_group_retry_notice(
    task: PerfGroupTask,
    child_groups: tuple[tuple[str, ...], ...],
    error: PerfStatError,
) -> str:
    reason = _summarize_retry_reason(error)
    children = " | ".join(_describe_group(group) for group in child_groups)
    return (
        f"retry     : {reason}; splitting failed group [{_describe_group(task.group)}] "
        f"into {children}"
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

    for part in parts[2:]:
        event_name = _match_known_event_name(part, known_events)
        if event_name is not None:
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

    for part in parts[2:]:
        event_name = _match_known_event_name(part, known_events)
        if event_name is not None:
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


def _build_group_request(
    request: ObservationRequest,
    group: tuple[str, ...],
) -> ObservationRequest:
    return ObservationRequest(
        statement=request.statement,
        pid=request.pid,
        comm=request.comm,
        events=group,
        interval_ms=request.interval_ms,
        history_size=request.history_size,
    )


def _plan_group_retry(
    task: PerfGroupTask,
    error: PerfStatError,
    *,
    retry_grouping: bool,
) -> tuple[tuple[tuple[str, ...], ...], int] | None:
    if not retry_grouping or len(task.group) <= 1 or not _is_retryable_grouping_error(error):
        return None

    next_slots = min(task.pmu_slots, len(task.group) - 1)
    while next_slots >= 1:
        child_groups = plan_event_groups(task.group, group_mode="auto", pmu_slots=next_slots)
        if child_groups != (task.group,):
            return child_groups, next_slots
        lowered_slots = _next_lower_slot_limit(next_slots)
        if lowered_slots is None:
            break
        next_slots = lowered_slots
    return None


@lru_cache(maxsize=1)
def detect_pmu_slot_limit() -> int:
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
    current_group: list[str] = []
    for event in ordered_events:
        if current_group and not _can_append_event(current_group, event, max_group_size=max_group_size):
            groups.append(tuple(current_group))
            current_group = []
        current_group.append(event)
    if current_group:
        groups.append(tuple(current_group))
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
            if _can_append_event(group, event, max_group_size=max_group_size):
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
                if _can_append_group(target_group, group, max_group_size=max_group_size):
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
        if _group_slot_cost(group) <= max_group_size:
            split_groups.append(list(group))
            continue
        split_groups.extend(list(chunk) for chunk in _chunk_groups(tuple(group), max_group_size=max_group_size))
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


def _describe_group(group: tuple[str, ...]) -> str:
    return ", ".join(group)


def _match_known_event_name(raw_event: str, known_events: Iterable[str]) -> str | None:
    known = tuple(dict.fromkeys(known_events))
    raw_cleaned = raw_event.strip().lower()
    cleaned = raw_cleaned.replace("_", "-")
    if not cleaned:
        return None

    normalized_event = normalize_event_name(raw_cleaned)
    if normalized_event is not None and normalized_event in known:
        return normalized_event

    if raw_cleaned in known:
        return raw_cleaned

    if cleaned in known:
        return cleaned

    for event in known:
        if ":" in event and (raw_cleaned.startswith(f"{event}:") or cleaned.startswith(f"{event}:")):
            return event
        if ":" not in event and ":" in raw_cleaned and raw_cleaned.rsplit(":", maxsplit=1)[0] == event:
            return event
        if ":" not in event and ":" in cleaned and cleaned.rsplit(":", maxsplit=1)[0] == event:
            return event
    return None


def _group_slot_cost(group: Iterable[str]) -> int:
    return sum(_event_slot_cost(event) for event in group)


def _can_append_event(group: Iterable[str], event: str, *, max_group_size: int) -> bool:
    return _group_slot_cost(group) + _event_slot_cost(event) <= max_group_size


def _can_append_group(target_group: Iterable[str], source_group: Iterable[str], *, max_group_size: int) -> bool:
    return _group_slot_cost(target_group) + _group_slot_cost(source_group) <= max_group_size


def _event_slot_cost(event: str) -> int:
    cleaned = event.strip().lower().replace("_", "-")
    if not cleaned:
        return 0
    if cleaned in SOFTWARE_EVENTS:
        return 0
    if cleaned.startswith("software:") or cleaned.startswith("tracepoint:"):
        return 0
    if ":" in cleaned:
        base_event = cleaned.split(":", maxsplit=1)[0]
        if normalize_event_name(base_event) is None:
            return 0
    return 1


def _add_partial_sample(
    buckets: list[_PendingSampleBucket],
    sample: PerfSample,
    *,
    tolerance: float,
) -> None:
    for bucket in buckets:
        if abs(bucket.timestamp_sec - sample.timestamp_sec) <= tolerance:
            bucket.values.update(sample.values)
            return

    buckets.append(_PendingSampleBucket(sample.timestamp_sec, dict(sample.values)))
    buckets.sort(key=lambda bucket: bucket.timestamp_sec)


def _pop_ready_samples(
    buckets: list[_PendingSampleBucket],
    *,
    newest_timestamp: float,
    tolerance: float,
) -> list[PerfSample]:
    ready: list[PerfSample] = []
    remaining: list[_PendingSampleBucket] = []
    cutoff = newest_timestamp - tolerance
    for bucket in buckets:
        if bucket.timestamp_sec < cutoff:
            ready.append(_build_sample(bucket.timestamp_sec, bucket.values))
        else:
            remaining.append(bucket)
    buckets[:] = remaining
    return ready


def _drain_pending_samples(buckets: list[_PendingSampleBucket]) -> list[PerfSample]:
    drained = [_build_sample(bucket.timestamp_sec, bucket.values) for bucket in buckets]
    buckets.clear()
    return drained
