from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from perf_skill.models import ObservationRequest, PerfSample, TargetProcess


@dataclass(frozen=True)
class MetricSummary:
    name: str
    sample_count: int
    first: float
    last: float
    average: float
    minimum: float
    maximum: float
    trend: str


@dataclass(frozen=True)
class RatioSummary:
    name: str
    value: float


@dataclass(frozen=True)
class ObservationSummary:
    pid: int
    comm: str
    sample_count: int
    duration_sec: float
    metrics: tuple[MetricSummary, ...]
    ratios: tuple[RatioSummary, ...]


@dataclass(frozen=True)
class PerfScriptRecord:
    comm: str
    pid: int
    tid: int
    cpu: int | None
    time_sec: float
    event: str
    symbol: str | None
    dso: str | None


@dataclass(frozen=True)
class PerfDataSummary:
    data_path: str
    sample_count: int
    duration_sec: float
    event_counts: tuple[tuple[str, int], ...]
    comm_counts: tuple[tuple[str, int], ...]
    symbol_counts: tuple[tuple[str, int], ...]


_PERF_SCRIPT_PATTERN = re.compile(
    r"^\s*(?P<comm>\S+)\s+"
    r"(?P<pid>\d+)(?:/(?P<tid>\d+))?\s+"
    r"\[(?P<cpu>\d+)\]\s+"
    r"(?P<time>\d+(?:\.\d+)?):\s+"
    r"(?P<event>\S+):"
    r"(?:\s+(?P<rest>.*))?$"
)

_SYMBOL_PATTERN = re.compile(
    r"^(?:(?P<ip>\S+)\s+)?(?P<symbol>.+?)(?:\s+\((?P<dso>[^)]+)\))?$"
)


def summarize_samples(
    request: ObservationRequest,
    target: TargetProcess,
    samples: list[PerfSample],
) -> ObservationSummary:
    metrics: list[MetricSummary] = []
    for metric_name in (*request.events, "ipc"):
        metric_values = _metric_values(samples, metric_name)
        if not metric_values:
            continue
        metrics.append(
            MetricSummary(
                name=metric_name,
                sample_count=len(metric_values),
                first=metric_values[0],
                last=metric_values[-1],
                average=sum(metric_values) / len(metric_values),
                minimum=min(metric_values),
                maximum=max(metric_values),
                trend=_trend_label(metric_values),
            )
        )

    ratios: list[RatioSummary] = []
    branch_ratio = _aggregate_ratio(samples, numerator="branch-misses", denominator="branches")
    if branch_ratio is not None:
        ratios.append(RatioSummary(name="branch-miss-rate", value=branch_ratio))
    cache_ratio = _aggregate_ratio(samples, numerator="cache-misses", denominator="cache-references")
    if cache_ratio is not None:
        ratios.append(RatioSummary(name="cache-miss-rate", value=cache_ratio))

    duration_sec = 0.0
    if len(samples) >= 2:
        duration_sec = max(0.0, samples[-1].timestamp_sec - samples[0].timestamp_sec)

    return ObservationSummary(
        pid=target.pid,
        comm=target.comm,
        sample_count=len(samples),
        duration_sec=duration_sec,
        metrics=tuple(metrics),
        ratios=tuple(ratios),
    )


def render_observation_summary(summary: ObservationSummary) -> str:
    lines = [
        f"summary   : {summary.sample_count} samples over {summary.duration_sec:.2f}s for pid={summary.pid} comm={summary.comm}"
    ]
    if summary.sample_count == 0:
        lines.append("summary   : no samples were captured")
        return "\n".join(lines)

    for metric in summary.metrics:
        lines.append(
            "metric    : "
            f"{metric.name} avg={_format_value(metric.average)} "
            f"peak={_format_value(metric.maximum)} "
            f"last={_format_value(metric.last)} "
            f"trend={metric.trend}"
        )
    for ratio in summary.ratios:
        lines.append(f"derived   : {ratio.name}={ratio.value * 100:.2f}%")
    return "\n".join(lines)


def parse_perf_script_line(line: str) -> PerfScriptRecord | None:
    match = _PERF_SCRIPT_PATTERN.match(line.rstrip())
    if match is None:
        return None

    rest = (match.group("rest") or "").strip()
    symbol = None
    dso = None
    if rest:
        symbol_match = _SYMBOL_PATTERN.match(rest)
        if symbol_match is not None:
            symbol = symbol_match.group("symbol") or None
            dso = symbol_match.group("dso") or None

    return PerfScriptRecord(
        comm=match.group("comm"),
        pid=int(match.group("pid")),
        tid=int(match.group("tid") or match.group("pid")),
        cpu=int(match.group("cpu")) if match.group("cpu") is not None else None,
        time_sec=float(match.group("time")),
        event=match.group("event"),
        symbol=symbol,
        dso=dso,
    )


def summarize_perf_script_output(
    data_path: str,
    script_output: str,
    *,
    top_n: int = 5,
) -> PerfDataSummary:
    records = [
        record
        for line in script_output.splitlines()
        if (record := parse_perf_script_line(line)) is not None
    ]

    event_counts = Counter(record.event for record in records)
    comm_counts = Counter(record.comm for record in records)
    symbol_counts = Counter(_symbol_key(record) for record in records if record.symbol is not None)

    duration_sec = 0.0
    if len(records) >= 2:
        duration_sec = max(0.0, records[-1].time_sec - records[0].time_sec)

    return PerfDataSummary(
        data_path=data_path,
        sample_count=len(records),
        duration_sec=duration_sec,
        event_counts=_top_items(event_counts, top_n),
        comm_counts=_top_items(comm_counts, top_n),
        symbol_counts=_top_items(symbol_counts, top_n),
    )


def render_perf_data_summary(summary: PerfDataSummary) -> str:
    lines = [
        f"data      : {summary.data_path}",
        f"summary   : {summary.sample_count} parsed samples over {summary.duration_sec:.2f}s",
    ]
    if summary.sample_count == 0:
        lines.append("summary   : no perf script samples were parsed")
        return "\n".join(lines)

    for name, count in summary.event_counts:
        lines.append(f"top-event : {name}={count}")
    for name, count in summary.comm_counts:
        lines.append(f"top-comm  : {name}={count}")
    for name, count in summary.symbol_counts:
        lines.append(f"top-sym   : {name}={count}")
    return "\n".join(lines)


def write_summary_json(output_path: str, summary: ObservationSummary | PerfDataSummary) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary), ensure_ascii=True, indent=2), encoding="utf-8")


def _metric_values(samples: list[PerfSample], metric_name: str) -> list[float]:
    if metric_name == "ipc":
        return [sample.ipc for sample in samples if sample.ipc is not None]
    return [sample.values[metric_name] for sample in samples if metric_name in sample.values]


def _aggregate_ratio(
    samples: list[PerfSample],
    *,
    numerator: str,
    denominator: str,
) -> float | None:
    numerator_total = sum(sample.values.get(numerator, 0.0) for sample in samples)
    denominator_total = sum(sample.values.get(denominator, 0.0) for sample in samples)
    if denominator_total <= 0.0:
        return None
    return numerator_total / denominator_total


def _trend_label(values: list[float]) -> str:
    if len(values) <= 1:
        return "stable"
    midpoint = max(1, len(values) // 2)
    start_window = values[:midpoint]
    end_window = values[midpoint:]
    start_avg = sum(start_window) / len(start_window)
    end_avg = sum(end_window) / len(end_window)
    delta = end_avg - start_avg

    if abs(delta) <= max(abs(start_avg) * 0.08, 1e-9):
        return "stable"
    if delta > 0:
        return "rising"
    return "falling"


def _format_value(value: float) -> str:
    if abs(value) >= 1000:
        suffixes = ["", "K", "M", "G", "T"]
        scaled = float(value)
        suffix_index = 0
        while abs(scaled) >= 1000 and suffix_index < len(suffixes) - 1:
            scaled /= 1000.0
            suffix_index += 1
        return f"{scaled:.2f}{suffixes[suffix_index]}"
    if value.is_integer():
        return f"{value:.0f}"
    return f"{value:.3f}"


def _top_items(counter: Counter[str], limit: int) -> tuple[tuple[str, int], ...]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return tuple(items[:limit])


def _symbol_key(record: PerfScriptRecord) -> str:
    if record.symbol is None:
        return "<unknown>"
    if record.dso is None:
        return record.symbol
    return f"{record.symbol} [{record.dso}]"