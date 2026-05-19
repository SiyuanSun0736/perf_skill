from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from perf_skill.models import ObservationError, ObservationRequest

EVENT_ALIASES = {
    "inst": "instructions",
    "insn": "instructions",
    "instruction": "instructions",
    "instructions": "instructions",
    "instr": "instructions",
    "指令": "instructions",
    "指令数": "instructions",
    "指令计数": "instructions",
    "cycles": "cycles",
    "cycle": "cycles",
    "周期": "cycles",
    "周期数": "cycles",
    "时钟周期": "cycles",
    "cpu周期": "cycles",
    "branches": "branches",
    "branch": "branches",
    "branchs": "branches",
    "分支": "branches",
    "branch-misses": "branch-misses",
    "branch_misses": "branch-misses",
    "分支未命中": "branch-misses",
    "分支预测失败": "branch-misses",
    "cache-misses": "cache-misses",
    "cache_misses": "cache-misses",
    "cache-miss": "cache-misses",
    "缓存未命中": "cache-misses",
    "cache-references": "cache-references",
    "cache_refs": "cache-references",
    "refs": "cache-references",
    "缓存引用": "cache-references",
    "缓存访问": "cache-references",
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

SOFTWARE_EVENT_NAMES = {
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

ACTION_TOKENS = {
    "trace",
    "track",
    "observe",
    "watch",
    "profile",
    "collect",
    "sample",
    "monitor",
    "inspect",
    "probe",
    "采样",
    "采",
    "探测",
    "追踪",
    "跟踪",
    "观测",
    "监控",
    "我要追踪",
    "我想追踪",
    "帮我追踪",
    "请追踪",
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
    "和",
    "与",
    "先",
    "再",
    "然后",
    "dry-run",
    "dryrun",
    "preview",
    "list",
    "show",
    "view",
    "available",
    "supported",
    "related",
    "all",
    "查看",
    "列出",
    "显示",
    "预览",
    "模拟",
    "支持",
    "相关",
    "哪些",
    "有哪些",
    "所有",
    "全部",
    "事件",
    "内",
    "之内",
    "以内",
    "我要",
    "我想",
    "帮我",
    "请",
    "一下",
    "下",
    "有",
    "并",
    "并且",
    "生成",
    "导出",
    "输出",
    "保存",
    "绘制",
    "画出",
    "图像",
    "图片",
    "图表",
    "曲线图",
    "趋势图",
    "image",
    "chart",
    "plot",
    "svg",
}

PID_KEYS = {"pid", "process-id", "processid", "process_id", "进程", "进程号"}
COMM_KEYS = {"comm", "name", "cmd", "command", "process-name", "进程名"}
EVENT_KEYS = {"event", "events", "metric", "metrics", "hw", "硬件事件", "事件"}
SAMPLE_KEYS = {"sample", "samples", "sample-count", "samplecount", "样本", "样本数", "采样次数", "次"}
DURATION_KEYS = {"s", "seconds", "second", "sec", "secs", "duration", "duration-sec", "时长", "持续", "秒", "秒钟"}
EVENT_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("instructions", "cycles"),
    ("branches", "branch-misses"),
    ("cache-references", "cache-misses"),
)
PREVIEW_HINT_TOKENS = ("dry-run", "dryrun", "preview", "预览", "模拟")
SVG_HINT_PATTERNS = (
    re.compile(r"(生成|导出|输出|保存|绘制|画出).*(图像|图片|图表|曲线图|趋势图|svg)"),
    re.compile(r"(图像|图片|图表|曲线图|趋势图|svg)"),
    re.compile(r"\b(image|chart|plot|svg)\b"),
)
PERF_DATA_RECORD_HINT_PATTERNS = (
    re.compile(r"(录制|记录|保存|输出|导出).*(perf\.data|\.data\b|data文件|data file)"),
    re.compile(r"\b(record)\b.*\b(perf\.data|data)\b"),
)
PERF_DATA_PARSE_HINT_PATTERNS = (
    re.compile(r"(解析|分析).*(perf\.data|\.data\b|data文件|data file)"),
    re.compile(r"\b(parse|analyze)\b.*\b(perf\.data|data)\b"),
)
LIST_EVENT_HINT_PATTERNS = (
    re.compile(r"\bperf\s+list\b"),
    re.compile(r"\b(list|show|view)\b.*\b(events?)\b"),
    re.compile(r"(查看|列出|显示).*(事件|硬件事件)"),
    re.compile(r"((有\s*哪些)|(支持\s*哪些)).*(pmu|events?|事件|硬件事件)"),
)
SAMPLE_PATTERNS = (
    re.compile(r"(?<!\d)(\d+)\s*(?:samples?|sample)\b"),
    re.compile(r"\b(?:samples?|sample)\s*(\d+)\b"),
    re.compile(r"采样\s*(\d+)\s*次"),
    re.compile(r"(?<!\d)(\d+)\s*次采样"),
    re.compile(r"(?<!\d)(\d+)\s*(?:个)?样本"),
)
DURATION_PATTERNS = (
    re.compile(r"(?<!\d)(\d+)\s*(?:s|sec|secs|second|seconds)\b"),
    re.compile(r"(?<!\d)(\d+)\s*秒"),
)
SAMPLE_TOKEN_PATTERNS = (
    re.compile(r"\d+(?:samples?|sample)\b"),
    re.compile(r"采样\d+次"),
    re.compile(r"\d+次采样"),
    re.compile(r"\d+(?:个)?样本"),
)
DURATION_TOKEN_PATTERNS = (
    re.compile(r"\d+(?:s|sec|secs|second|seconds)\b"),
    re.compile(r"\d+秒"),
)


@dataclass(frozen=True)
class ParsedObservation:
    pid: int | None
    comm: str | None
    events: tuple[str, ...]
    mentioned_events: tuple[str, ...]
    sample_count: int | None
    duration_sec: int | None
    wants_dry_run: bool
    wants_svg: bool
    wants_perf_data: bool
    wants_parse_data: bool
    data_path: str | None
    wants_event_list: bool
    event_filters: tuple[str, ...]


def build_request(
    statement: str,
    *,
    pid: int | None,
    comm: str | None,
    extra_events: list[str] | None,
    interval_ms: int,
    history_size: int,
    parsed: ParsedObservation | None = None,
) -> ObservationRequest:
    parsed_observation = parsed or parse_observation_statement(statement)

    resolved_events = parsed_observation.events or normalize_events(())
    if extra_events:
        resolved_events = normalize_events(tuple(extra_events))

    request = ObservationRequest(
        statement=statement,
        pid=pid if pid is not None else parsed_observation.pid,
        comm=comm if comm is not None else parsed_observation.comm,
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
    parsed = parse_observation_statement(statement)
    return parsed.pid, parsed.comm, parsed.events or normalize_events(())


def parse_observation_statement(statement: str) -> ParsedObservation:
    statement = _normalize_statement(statement)
    if not statement:
        return ParsedObservation(
            pid=None,
            comm=None,
            events=normalize_events(()),
            mentioned_events=(),
            sample_count=None,
            duration_sec=None,
            wants_dry_run=False,
            wants_svg=False,
            wants_perf_data=False,
            wants_parse_data=False,
            data_path=None,
            wants_event_list=False,
            event_filters=(),
        )

    sample_count = _extract_count_hint(statement, SAMPLE_PATTERNS, label="samples")
    duration_sec = _extract_count_hint(statement, DURATION_PATTERNS, label="seconds")
    wants_dry_run = _has_hint(statement, PREVIEW_HINT_TOKENS)
    wants_svg = _has_svg_intent(statement)
    wants_perf_data = _has_perf_data_record_intent(statement)
    wants_parse_data = _has_perf_data_parse_intent(statement)
    data_path = _extract_data_path(statement)
    wants_event_list = _has_list_event_intent(statement)

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

        if sample_count is not None:
            consumed = _consume_hint_tokens(tokens, index, SAMPLE_KEYS, SAMPLE_TOKEN_PATTERNS)
            if consumed is not None:
                index += consumed
                continue

        if duration_sec is not None:
            consumed = _consume_hint_tokens(tokens, index, DURATION_KEYS, DURATION_TOKEN_PATTERNS)
            if consumed is not None:
                index += consumed
                continue

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

        if lowered_key in SAMPLE_KEYS:
            sample_value, consumed = _extract_inline_or_next(value, tokens, index)
            sample_count = _parse_positive_int(sample_value, label="samples")
            index += consumed
            continue

        if lowered_key in DURATION_KEYS:
            duration_value, consumed = _extract_inline_or_next(value, tokens, index)
            duration_sec = _parse_duration_value(duration_value)
            index += consumed
            continue

        normalized_event = normalize_event_name(token)
        if normalized_event is not None:
            events.append(normalized_event)
        else:
            split_events = _split_event_values(token)
            if split_events:
                events.extend(split_events)
            else:
                unknowns.append(_clean_value(token))
        index += 1

    for token in unknowns:
        if not token:
            continue
        if wants_event_list:
            continue
        if pid is None and token.isdigit():
            pid = int(token)
            continue
        if comm is None:
            comm = token

    mentioned_events = tuple(dict.fromkeys(events))
    resolved_events = normalize_events(tuple(events)) if events or not wants_event_list else ()

    return ParsedObservation(
        pid=pid,
        comm=comm,
        events=resolved_events,
        mentioned_events=mentioned_events,
        sample_count=sample_count,
        duration_sec=duration_sec,
        wants_dry_run=wants_dry_run,
        wants_svg=wants_svg,
        wants_perf_data=wants_perf_data,
        wants_parse_data=wants_parse_data,
        data_path=data_path,
        wants_event_list=wants_event_list,
        event_filters=_build_event_filters(mentioned_events, unknowns),
    )


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
    raw_token = _clean_value(raw_event).lower()
    token = raw_token.replace("_", "-")
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
    if token in SOFTWARE_EVENT_NAMES:
        return token
    if ":" in token:
        base_token = token.split(":", maxsplit=1)[0]
        normalized_base = normalize_event_name(base_token)
        if normalized_base is not None:
            return normalized_base
        if _looks_like_tracepoint_event(raw_token):
            return raw_token
    return None


def _normalize_statement(statement: str) -> str:
    normalized = statement.strip()
    replacements = {
        "，": ",",
        "、": ",",
        "：": ":",
        "；": " ",
        "。": " ",
        "（": " ",
        "）": " ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = normalized.replace(",", ", ")
    pattern_replacements = (
        (r"(我要|我想|帮我|请)\s*(追踪|跟踪|观测|监控)", r"\2 "),
        (r"(查看|列出|显示|支持)哪些", r"\1 哪些"),
        (r"有哪些", "有 哪些"),
        (r"采样(?=\d)", "采样 "),
        (r"采(?=\d)", "采 "),
        (r"持续(?=\d)", "持续 "),
        (r"(秒钟?|样本|次)(之内|以内|内)", r"\1 内"),
        (r"内的", "内 的"),
        (r"个样本", "样本"),
    )
    for pattern, replacement in pattern_replacements:
        normalized = re.sub(pattern, replacement, normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])", " ", normalized)
    normalized = re.sub(r"(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])", " ", normalized)
    normalized = re.sub(
        r"([A-Za-z][A-Za-z0-9_.-]*?)(\d+)(?=\s*(?:秒钟?|s\b|sec\b|secs\b|second\b|seconds\b|sample\b|samples\b|样本|次\b))",
        r"\1 \2",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _has_hint(statement: str, hints: tuple[str, ...]) -> bool:
    lowered = statement.lower()
    return any(hint in lowered for hint in hints)


def _has_svg_intent(statement: str) -> bool:
    lowered = statement.lower()
    return any(pattern.search(lowered) for pattern in SVG_HINT_PATTERNS)


def _has_perf_data_record_intent(statement: str) -> bool:
    lowered = statement.lower()
    return any(pattern.search(lowered) for pattern in PERF_DATA_RECORD_HINT_PATTERNS)


def _has_perf_data_parse_intent(statement: str) -> bool:
    lowered = statement.lower()
    return any(pattern.search(lowered) for pattern in PERF_DATA_PARSE_HINT_PATTERNS)


def _has_list_event_intent(statement: str) -> bool:
    lowered = statement.lower()
    return any(pattern.search(lowered) for pattern in LIST_EVENT_HINT_PATTERNS)


def _extract_count_hint(
    statement: str,
    patterns: tuple[re.Pattern[str], ...],
    *,
    label: str,
) -> int | None:
    lowered = statement.lower()
    for pattern in patterns:
        match = pattern.search(lowered)
        if match is not None:
            return _parse_positive_int(match.group(1), label=label)
    return None


def _extract_data_path(statement: str) -> str | None:
    for token in shlex.split(statement):
        cleaned = _clean_value(token)
        lowered = cleaned.lower()
        if lowered.endswith(".data") or lowered == "perf.data":
            return cleaned
    return None


def _consume_hint_tokens(
    tokens: list[str],
    index: int,
    keys: set[str],
    token_patterns: tuple[re.Pattern[str], ...],
) -> int | None:
    token = _clean_value(tokens[index]).lower()
    if any(pattern.fullmatch(token) for pattern in token_patterns):
        return 1

    next_token = _clean_value(tokens[index + 1]).lower() if index + 1 < len(tokens) else ""
    if token.isdigit() and next_token in keys:
        return 2
    if token in keys and next_token.isdigit():
        return 2
    if token in keys:
        return 1
    return None


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


def _parse_positive_int(raw_value: str, *, label: str) -> int:
    cleaned = _clean_value(raw_value)
    if not cleaned.isdigit() or int(cleaned) <= 0:
        raise ObservationError(f"{label} must be a positive integer")
    return int(cleaned)


def _parse_duration_value(raw_value: str) -> int:
    cleaned = _clean_value(raw_value).lower()
    match = re.fullmatch(r"(\d+)(?:s|sec|secs|second|seconds|秒)?", cleaned)
    if match is None:
        raise ObservationError(f"invalid seconds value: {raw_value}")
    return _parse_positive_int(match.group(1), label="seconds")


def _build_event_filters(
    mentioned_events: tuple[str, ...],
    unknowns: list[str],
) -> tuple[str, ...]:
    filters: list[str] = [_event_filter_term(event) for event in mentioned_events]
    seen = set(filters)
    for token in unknowns:
        cleaned = _clean_value(token).lower().replace("_", "-")
        if not cleaned or cleaned.isdigit():
            continue
        if cleaned in ACTION_TOKENS or cleaned in STOP_TOKENS:
            continue
        if cleaned in PID_KEYS or cleaned in COMM_KEYS or cleaned in EVENT_KEYS:
            continue
        if cleaned.endswith("事件"):
            continue
        if cleaned not in seen:
            filters.append(cleaned)
            seen.add(cleaned)
    return tuple(filters)


def _event_filter_term(event: str) -> str:
    return {
        "branches": "branch",
        "cache-references": "cache",
    }.get(event, event)


def _looks_like_tracepoint_event(raw_token: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_.-]+", raw_token))


def _clean_value(raw_value: str) -> str:
    return raw_value.strip().strip(",").strip("\"").strip("'")
