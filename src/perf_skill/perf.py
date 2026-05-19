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


def build_perf_command(request: ObservationRequest, target: TargetProcess) -> list[str]:
    return [
        "perf",
        "stat",
        "--interval-print",
        str(request.interval_ms),
        "--no-big-num",
        "-x",
        ",",
        "-e",
        ",".join(request.events),
        "-p",
        str(target.pid),
    ]


def stream_perf_samples(
    request: ObservationRequest,
    target: TargetProcess,
) -> Iterator[PerfSample]:
    command = build_perf_command(request, target)
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
            return PerfStatus(timestamp_sec=timestamp, event=event_name, status=status.strip("<>") )
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
