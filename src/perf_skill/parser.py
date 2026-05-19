from __future__ import annotations

import shlex

from perf_skill.models import ObservationError, ObservationRequest

EVENT_ALIASES = {
    "inst": "instructions",
    "insn": "instructions",
    "instruction": "instructions",
    "instructions": "instructions",
    "instr": "instructions",
    "cycles": "cycles",
    "cycle": "cycles",
    "branches": "branches",
    "branch": "branches",
    "branch-misses": "branch-misses",
    "branch_misses": "branch-misses",
    "cache-misses": "cache-misses",
    "cache_misses": "cache-misses",
    "cache-miss": "cache-misses",
    "cache-references": "cache-references",
    "cache_refs": "cache-references",
    "refs": "cache-references",
    "instructions:u": "instructions",
    "cycles:u": "cycles",
    "branches:u": "branches",
    "branch-misses:u": "branch-misses",
    "cache-misses:u": "cache-misses",
    "cache-references:u": "cache-references",
    "zhiling": "instructions",
    "zhilingshu": "instructions",
    "zhouqi": "cycles",
}

ACTION_TOKENS = {
    "trace",
    "track",
    "observe",
    "watch",
    "profile",
    "collect",
    "sample",
    "monitor",
    "追踪",
    "跟踪",
    "观测",
    "监控",
}

STOP_TOKENS = {
    "of",
    "for",
    "the",
    "process",
    "and",
    "with",
    "on",
    "target",
    "metrics",
    "metric",
    "hardware",
    "events",
    "event",
    "de",
    "d",
    "which",
    "what",
    "or",
    "pids",
    "comms",
    "的",
}

PID_KEYS = {"pid", "process-id", "processid", "process_id", "进程", "进程号"}
COMM_KEYS = {"comm", "name", "cmd", "command", "process-name", "进程名"}
EVENT_KEYS = {"event", "events", "metric", "metrics", "hw", "硬件事件", "事件"}
EVENT_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("instructions", "cycles"),
    ("branches", "branch-misses"),
    ("cache-references", "cache-misses"),
)


def build_request(
    statement: str,
    *,
    pid: int | None,
    comm: str | None,
    extra_events: list[str] | None,
    interval_ms: int,
    history_size: int,
) -> ObservationRequest:
    parsed_pid, parsed_comm, parsed_events = parse_statement(statement)

    resolved_events = parsed_events
    if extra_events:
        resolved_events = normalize_events(tuple(extra_events))

    request = ObservationRequest(
        statement=statement,
        pid=pid if pid is not None else parsed_pid,
        comm=comm if comm is not None else parsed_comm,
        events=resolved_events,
        interval_ms=interval_ms,
        history_size=history_size,
    )

    if request.pid is None and request.comm is None:
        raise ObservationError("missing target: specify pid, comm, or both")
    if request.interval_ms <= 0:
        raise ObservationError("interval-ms must be greater than zero")
    if request.history_size <= 0:
        raise ObservationError("history must be greater than zero")
    return request


def parse_statement(statement: str) -> tuple[int | None, str | None, tuple[str, ...]]:
    statement = _normalize_statement(statement)
    if not statement:
        return None, None, normalize_events(())

    tokens = shlex.split(statement)
    pid: int | None = None
    comm: str | None = None
    events: list[str] = []
    unknowns: list[str] = []

    index = 0
    while index < len(tokens):
        raw_token = tokens[index]
        token = raw_token.strip()
        lowered = token.lower()

        if lowered in ACTION_TOKENS or lowered in STOP_TOKENS:
            index += 1
            continue

        key, separator, value = _partition_token(token)
        lowered_key = key.lower()

        if lowered_key in PID_KEYS:
            pid_value, consumed = _extract_inline_or_next(value, tokens, index)
            pid = _parse_pid(pid_value)
            index += consumed
            continue

        if lowered_key in COMM_KEYS:
            comm_value, consumed = _extract_inline_or_next(value, tokens, index)
            comm = _clean_value(comm_value)
            index += consumed
            continue

        if lowered_key in EVENT_KEYS:
            event_value, consumed = _extract_inline_or_next(value, tokens, index)
            events.extend(_split_event_values(event_value))
            index += consumed
            continue

        normalized_event = normalize_event_name(token)
        if normalized_event is not None:
            events.append(normalized_event)
        else:
            unknowns.append(_clean_value(token))
        index += 1

    for token in unknowns:
        if not token:
            continue
        if pid is None and token.isdigit():
            pid = int(token)
            continue
        if comm is None:
            comm = token

    return pid, comm, normalize_events(tuple(events))


def normalize_events(raw_events: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_event in raw_events:
        normalized_event = normalize_event_name(raw_event)
        if normalized_event is None or normalized_event in seen:
            continue
        normalized.append(normalized_event)
        seen.add(normalized_event)

    if not normalized:
        normalized = ["instructions", "cycles"]
    else:
        if "instructions" not in seen:
            normalized.insert(0, "instructions")
        if "cycles" not in seen:
            insert_index = 1 if normalized and normalized[0] == "instructions" else 0
            normalized.insert(insert_index, "cycles")

    return tuple(_expand_event_families(normalized))


def normalize_event_name(raw_event: str) -> str | None:
    token = _clean_value(raw_event).lower().replace("_", "-")
    if not token:
        return None
    if token in EVENT_ALIASES:
        return EVENT_ALIASES[token]
    if token in {
        "instructions",
        "cycles",
        "branches",
        "branch-misses",
        "cache-misses",
        "cache-references",
    }:
        return token
    if ":" in token:
        base_token = token.split(":", maxsplit=1)[0]
        return normalize_event_name(base_token)
    return None


def _normalize_statement(statement: str) -> str:
    normalized = statement.strip()
    replacements = {
        "，": ",",
        "：": ":",
        "；": " ",
        "。": " ",
        "（": " ",
        "）": " ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _partition_token(token: str) -> tuple[str, str, str]:
    for separator in ("=", ":"):
        if separator in token:
            left, right = token.split(separator, maxsplit=1)
            return left, separator, right
    return token, "", ""


def _extract_inline_or_next(value: str, tokens: list[str], index: int) -> tuple[str, int]:
    if value:
        return value, 1
    next_index = index + 1
    if next_index >= len(tokens):
        raise ObservationError(f"missing value after {tokens[index]}")
    return tokens[next_index], 2


def _split_event_values(raw_value: str) -> list[str]:
    values: list[str] = []
    for token in raw_value.replace("+", ",").split(","):
        normalized_event = normalize_event_name(token)
        if normalized_event is not None:
            values.append(normalized_event)
    return values


def _expand_event_families(events: list[str]) -> list[str]:
    expanded = list(events)
    for family in EVENT_FAMILIES:
        positions = [expanded.index(event) for event in family if event in expanded]
        if not positions:
            continue

        anchor = min(positions)
        for event in family:
            if event in expanded:
                expanded.remove(event)
        for offset, event in enumerate(family):
            expanded.insert(anchor + offset, event)
    return expanded


def _parse_pid(raw_value: str) -> int:
    cleaned = _clean_value(raw_value)
    if not cleaned.isdigit():
        raise ObservationError(f"invalid pid: {raw_value}")
    return int(cleaned)


def _clean_value(raw_value: str) -> str:
    return raw_value.strip().strip(",").strip("\"").strip("'")
