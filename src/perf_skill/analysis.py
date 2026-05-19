from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
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
class ExpertInsight:
    category: str
    headline: str
    detail: str
    recommendation: str | None


@dataclass(frozen=True)
class ObservationAnomaly:
    timestamp_sec: float
    metric: str
    kind: str
    baseline: float
    current: float
    delta_ratio: float | None


@dataclass(frozen=True)
class ObservationSummary:
    pid: int
    comm: str
    sample_count: int
    duration_sec: float
    metrics: tuple[MetricSummary, ...]
    ratios: tuple[RatioSummary, ...]
    anomalies: tuple[ObservationAnomaly, ...]
    insights: tuple[ExpertInsight, ...]


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
    callchain: tuple[str, ...]


@dataclass(frozen=True)
class PerfDataSummary:
    data_path: str
    sample_count: int
    duration_sec: float
    event_counts: tuple[tuple[str, int], ...]
    comm_counts: tuple[tuple[str, int], ...]
    thread_counts: tuple[tuple[str, int], ...]
    callchain_counts: tuple[tuple[str, int], ...]
    event_callchain_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    symbol_counts: tuple[tuple[str, int], ...]
    hotspots: tuple[tuple[str, int, float], ...]
    insights: tuple[ExpertInsight, ...]


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

    anomalies = _detect_observation_anomalies(samples)
    insights = _build_observation_insights(target, metrics, ratios, anomalies)

    return ObservationSummary(
        pid=target.pid,
        comm=target.comm,
        sample_count=len(samples),
        duration_sec=duration_sec,
        metrics=tuple(metrics),
        ratios=tuple(ratios),
        anomalies=anomalies,
        insights=insights,
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
    for anomaly in summary.anomalies:
        lines.append(render_observation_anomaly(anomaly))
    for insight in summary.insights:
        lines.extend(_render_insight(insight))
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
        callchain=(),
    )


def parse_perf_script_records(script_output: str) -> tuple[PerfScriptRecord, ...]:
    records: list[PerfScriptRecord] = []
    current_record: PerfScriptRecord | None = None
    current_callchain: list[tuple[str, str | None, str | None]] = []

    for raw_line in script_output.splitlines():
        if not raw_line.strip():
            continue

        record = parse_perf_script_line(raw_line)
        if record is not None:
            if current_record is not None:
                records.append(_finalize_perf_script_record(current_record, current_callchain))
            current_record = record
            current_callchain = []
            continue

        if current_record is not None and raw_line[:1].isspace():
            frame = _parse_perf_script_frame(raw_line)
            if frame is not None:
                current_callchain.append(frame)

    if current_record is not None:
        records.append(_finalize_perf_script_record(current_record, current_callchain))

    return tuple(records)


def detect_live_anomalies(samples: list[PerfSample]) -> tuple[ObservationAnomaly, ...]:
    if not samples:
        return ()
    latest_timestamp = samples[-1].timestamp_sec
    return tuple(
        anomaly
        for anomaly in _detect_observation_anomalies(samples)
        if abs(anomaly.timestamp_sec - latest_timestamp) <= 1e-9
    )


def render_observation_anomaly(anomaly: ObservationAnomaly) -> str:
    return _render_anomaly(anomaly)


def format_live_anomaly(anomaly: ObservationAnomaly) -> str:
    baseline = _format_anomaly_value(anomaly.metric, anomaly.baseline)
    current = _format_anomaly_value(anomaly.metric, anomaly.current)
    delta = "n/a" if anomaly.delta_ratio is None else f"{anomaly.delta_ratio * 100:+.1f}%"
    return f"{anomaly.metric} {anomaly.kind} {baseline}->{current} ({delta})"


def summarize_perf_script_output(
    data_path: str,
    script_output: str,
    *,
    top_n: int = 5,
) -> PerfDataSummary:
    records = list(parse_perf_script_records(script_output))

    event_counts = Counter(record.event for record in records)
    comm_counts = Counter(record.comm for record in records)
    thread_counts = Counter(_thread_key(record) for record in records)
    callchain_counts = Counter(
        _callchain_key(record.callchain)
        for record in records
        if record.callchain
    )
    event_callchain_counts = _group_event_callchain_counts(records, top_n)
    symbol_counts = Counter(_symbol_key(record) for record in records if record.symbol is not None)

    duration_sec = 0.0
    if len(records) >= 2:
        duration_sec = max(0.0, records[-1].time_sec - records[0].time_sec)

    hotspots = _build_hotspots(symbol_counts, len(records), top_n)
    insights = _build_perf_data_insights(
        data_path,
        len(records),
        event_counts,
        thread_counts,
        hotspots,
    )

    return PerfDataSummary(
        data_path=data_path,
        sample_count=len(records),
        duration_sec=duration_sec,
        event_counts=_top_items(event_counts, top_n),
        comm_counts=_top_items(comm_counts, top_n),
        thread_counts=_top_items(thread_counts, top_n),
        callchain_counts=_top_items(callchain_counts, top_n),
        event_callchain_counts=event_callchain_counts,
        symbol_counts=_top_items(symbol_counts, top_n),
        hotspots=hotspots,
        insights=insights,
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
    for name, count in summary.thread_counts:
        lines.append(f"top-thread: {name}={count}")
    for name, count in summary.callchain_counts:
        lines.append(f"top-callchain: {name}={count}")
    for event_name, callchains in summary.event_callchain_counts:
        for name, count in callchains:
            lines.append(f"top-callchain[{event_name}]: {name}={count}")
    for name, count in summary.symbol_counts:
        lines.append(f"top-sym   : {name}={count}")
    for name, count, share in summary.hotspots:
        lines.append(f"hotspot   : {name} samples={count} share={share * 100:.2f}%")
    for insight in summary.insights:
        lines.extend(_render_insight(insight))
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


def _parse_perf_script_frame(raw_line: str) -> tuple[str, str | None, str | None] | None:
    cleaned = raw_line.strip()
    if not cleaned:
        return None

    symbol_match = _SYMBOL_PATTERN.match(cleaned)
    if symbol_match is None:
        return cleaned, cleaned, None

    symbol = symbol_match.group("symbol") or cleaned
    dso = symbol_match.group("dso") or None
    return _render_frame(symbol, dso), symbol, dso


def _finalize_perf_script_record(
    record: PerfScriptRecord,
    callchain_frames: list[tuple[str, str | None, str | None]],
) -> PerfScriptRecord:
    if not callchain_frames:
        return record

    callchain = tuple(frame for frame, _, _ in callchain_frames)
    updated = replace(record, callchain=callchain)
    if updated.symbol is not None:
        return updated

    _, symbol, dso = callchain_frames[0]
    return replace(updated, symbol=symbol, dso=dso)


def _build_observation_insights(
    target: TargetProcess,
    metrics: list[MetricSummary],
    ratios: list[RatioSummary],
    anomalies: tuple[ObservationAnomaly, ...],
) -> tuple[ExpertInsight, ...]:
    insights: list[ExpertInsight] = []
    metric_by_name = {metric.name: metric for metric in metrics}
    ratio_by_name = {ratio.name: ratio for ratio in ratios}

    ipc = metric_by_name.get("ipc")
    cache_miss_rate = ratio_by_name.get("cache-miss-rate")
    branch_miss_rate = ratio_by_name.get("branch-miss-rate")
    cache_miss_anomaly = _latest_anomaly(anomalies, metric="cache-miss-rate", kind="surge")
    branch_miss_anomaly = _latest_anomaly(anomalies, metric="branch-miss-rate", kind="surge")
    follow_up = _perf_record_recommendation(target)

    if ipc is not None and ipc.average < 0.75:
        detail = (
            f"average IPC is {ipc.average:.3f}, so the CPU is retiring little work per cycle and is "
            "likely stalled on memory access or branch recovery."
        )
        recommendation = follow_up
        if cache_miss_rate is not None and cache_miss_rate.value >= 0.20:
            recommendation = (
                f"{follow_up}; prioritize pointer chasing, poor locality, or oversized working sets "
                "on the hottest path."
            )
        elif branch_miss_rate is not None and branch_miss_rate.value >= 0.08:
            recommendation = (
                f"{follow_up}; prioritize unpredictable branches, virtual dispatch, and hot if/else chains."
            )
        insights.append(
            ExpertInsight(
                category="low-ipc",
                headline="CPU throughput is low",
                detail=detail,
                recommendation=recommendation,
            )
        )

    cache_focus_value = None
    if cache_miss_rate is not None and cache_miss_rate.value >= 0.20:
        cache_focus_value = cache_miss_rate.value
    elif cache_miss_anomaly is not None:
        cache_focus_value = cache_miss_anomaly.current

    if cache_focus_value is not None:
        insights.append(
            ExpertInsight(
                category="cache-miss-rate",
                headline="Cache misses are dominating",
                detail=(
                    f"cache-miss-rate reached {cache_focus_value * 100:.2f}%, which usually points to "
                    "non-contiguous memory access, pointer-heavy traversal, or a working set that outgrows cache."
                ),
                recommendation=(
                    "Inspect the hottest allocation and traversal paths for linked structures, random lookups, "
                    "or poor data locality."
                ),
            )
        )

    branch_focus_value = None
    if branch_miss_rate is not None and branch_miss_rate.value >= 0.08:
        branch_focus_value = branch_miss_rate.value
    elif branch_miss_anomaly is not None:
        branch_focus_value = branch_miss_anomaly.current

    if branch_focus_value is not None:
        insights.append(
            ExpertInsight(
                category="branch-miss-rate",
                headline="Branch prediction is unstable",
                detail=(
                    f"branch-miss-rate reached {branch_focus_value * 100:.2f}%, so the CPU is probably "
                    "paying for unpredictable if/else paths, polymorphic dispatch, or mixed hot and cold logic."
                ),
                recommendation=(
                    "Inspect the hottest branch-heavy code paths and consider splitting fast paths from rare cases."
                ),
            )
        )

    if anomalies:
        first = anomalies[0]
        insights.append(
            ExpertInsight(
                category="transient-anomaly",
                headline="The stall is bursty rather than constant",
                detail=(
                    f"The first anomaly appears at {first.timestamp_sec:.2f}s where {first.metric} {first.kind}s "
                    "relative to its recent baseline, which usually means a phase shift or intermittent stall."
                ),
                recommendation=(
                    f"Try to reproduce the burst around {first.timestamp_sec:.2f}s and then {follow_up} to capture "
                    "the responsible call stacks."
                ),
            )
        )

    if insights:
        return tuple(insights)

    return (
        ExpertInsight(
            category="no-clear-pmu-bottleneck",
            headline="No dominant PMU-side bottleneck stands out",
            detail=(
                "IPC and miss rates stayed in a moderate band for this sample, so the slowdown may be in locks, "
                "syscalls, I/O wait, or a phase that this short run did not capture."
            ),
            recommendation=(
                "Sample for longer, or pair this run with scheduling and syscall visibility before chasing micro-ops."
            ),
        ),
    )


def _build_hotspots(
    symbol_counts: Counter[str],
    sample_count: int,
    limit: int,
) -> tuple[tuple[str, int, float], ...]:
    if sample_count <= 0:
        return ()
    return tuple(
        (name, count, count / sample_count)
        for name, count in _top_items(symbol_counts, limit)
    )


def _group_event_callchain_counts(
    records: list[PerfScriptRecord],
    limit: int,
) -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    grouped: dict[str, Counter[str]] = {}
    for record in records:
        if not record.callchain:
            continue
        event_counter = grouped.setdefault(record.event, Counter())
        event_counter[_callchain_key(record.callchain)] += 1

    return tuple(
        (event_name, _top_items(counter, limit))
        for event_name, counter in sorted(grouped.items())
    )


def _build_perf_data_insights(
    data_path: str,
    sample_count: int,
    event_counts: Counter[str],
    thread_counts: Counter[str],
    hotspots: tuple[tuple[str, int, float], ...],
) -> tuple[ExpertInsight, ...]:
    if sample_count <= 0:
        return ()

    insights: list[ExpertInsight] = []

    if hotspots:
        hottest_name, hottest_count, hottest_share = hotspots[0]
        top_three_share = sum(share for _, _, share in hotspots[:3])
        if hottest_share >= 0.30:
            insights.append(
                ExpertInsight(
                    category="hotspot-concentration",
                    headline="One symbol dominates the recorded time",
                    detail=(
                        f"{hottest_name} accounts for {hottest_share * 100:.2f}% of parsed samples, so it is the "
                        "first place to inspect at source or assembly level."
                    ),
                    recommendation=(
                        f"Inspect it with perf annotate --stdio -i {data_path} --symbol '{_annotation_symbol(hottest_name)}'."
                    ),
                )
            )
        if top_three_share >= 0.60:
            insights.append(
                ExpertInsight(
                    category="top-three-hotspots",
                    headline="The hot path is concentrated in a small set of functions",
                    detail=(
                        f"The top three symbols cover {top_three_share * 100:.2f}% of parsed samples, so a focused "
                        "review of those frames should explain most of the runtime."
                    ),
                    recommendation="Walk the top three hotspots in order before expanding to lower-ranked frames.",
                )
            )

    top_event = _top_items(event_counts, 1)
    if top_event and top_event[0][0] == "sched:sched_switch" and top_event[0][1] / sample_count >= 0.30:
        insights.append(
            ExpertInsight(
                category="scheduler-heavy",
                headline="Scheduling activity is a large part of the trace",
                detail=(
                    "A large share of samples landed in sched:sched_switch, which often means the workload spends "
                    "meaningful time being preempted, blocked, or bounced across runnable threads."
                ),
                recommendation="Inspect runnable contention, blocking points, or oversubscription before tuning instructions.",
            )
        )

    top_thread = _top_items(thread_counts, 1)
    if top_thread and top_thread[0][1] / sample_count >= 0.50:
        insights.append(
            ExpertInsight(
                category="thread-concentration",
                headline="One thread owns most of the samples",
                detail=(
                    f"{top_thread[0][0]} accounts for {top_thread[0][1] / sample_count * 100:.2f}% of parsed samples, "
                    "so the issue is likely localized instead of evenly spread across the process."
                ),
                recommendation="Keep following the hottest thread before broadening the investigation to the rest of the process.",
            )
        )

    return tuple(insights)


def _perf_record_recommendation(target: TargetProcess) -> str:
    return f"capture call stacks with perf record -g -p {target.pid} -- sleep 15"


def _detect_observation_anomalies(samples: list[PerfSample]) -> tuple[ObservationAnomaly, ...]:
    anomalies: list[ObservationAnomaly] = []
    anomalies.extend(_detect_series_drop(_metric_series(samples, "ipc"), metric="ipc"))
    anomalies.extend(
        _detect_series_surge(
            _ratio_series(samples, numerator="branch-misses", denominator="branches"),
            metric="branch-miss-rate",
        )
    )
    anomalies.extend(
        _detect_series_surge(
            _ratio_series(samples, numerator="cache-misses", denominator="cache-references"),
            metric="cache-miss-rate",
        )
    )
    anomalies.sort(key=lambda anomaly: anomaly.timestamp_sec)
    return tuple(anomalies)


def _metric_series(samples: list[PerfSample], metric: str) -> list[tuple[float, float]]:
    if metric == "ipc":
        return [
            (sample.timestamp_sec, sample.ipc)
            for sample in samples
            if sample.ipc is not None
        ]
    return [
        (sample.timestamp_sec, sample.values[metric])
        for sample in samples
        if metric in sample.values
    ]


def _ratio_series(
    samples: list[PerfSample],
    *,
    numerator: str,
    denominator: str,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for sample in samples:
        denominator_value = sample.values.get(denominator)
        numerator_value = sample.values.get(numerator)
        if denominator_value in (None, 0.0) or numerator_value is None:
            continue
        points.append((sample.timestamp_sec, numerator_value / denominator_value))
    return points


def _detect_series_drop(
    points: list[tuple[float, float]],
    *,
    metric: str,
) -> list[ObservationAnomaly]:
    anomalies: list[ObservationAnomaly] = []
    for index in range(2, len(points)):
        baseline_values = [value for _, value in points[max(0, index - 3):index]]
        if len(baseline_values) < 2:
            continue
        baseline = sum(baseline_values) / len(baseline_values)
        _, current = points[index]
        if baseline <= 0.0:
            continue
        if current <= baseline * 0.7 and (baseline - current) >= max(baseline * 0.15, 0.08):
            anomalies.append(
                ObservationAnomaly(
                    timestamp_sec=points[index][0],
                    metric=metric,
                    kind="drop",
                    baseline=baseline,
                    current=current,
                    delta_ratio=(current - baseline) / baseline,
                )
            )
    return anomalies


def _detect_series_surge(
    points: list[tuple[float, float]],
    *,
    metric: str,
) -> list[ObservationAnomaly]:
    anomalies: list[ObservationAnomaly] = []
    for index in range(2, len(points)):
        baseline_values = [value for _, value in points[max(0, index - 3):index]]
        if len(baseline_values) < 2:
            continue
        baseline = sum(baseline_values) / len(baseline_values)
        _, current = points[index]
        threshold = 0.05 if baseline <= 0.0 else baseline * 1.8
        min_delta = 0.03 if baseline <= 0.0 else 0.02
        if current >= threshold and (current - baseline) >= min_delta:
            delta_ratio = None if baseline <= 0.0 else (current - baseline) / baseline
            anomalies.append(
                ObservationAnomaly(
                    timestamp_sec=points[index][0],
                    metric=metric,
                    kind="surge",
                    baseline=baseline,
                    current=current,
                    delta_ratio=delta_ratio,
                )
            )
    return anomalies


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


def _render_anomaly(anomaly: ObservationAnomaly) -> str:
    baseline = _format_anomaly_value(anomaly.metric, anomaly.baseline)
    current = _format_anomaly_value(anomaly.metric, anomaly.current)
    delta = "n/a" if anomaly.delta_ratio is None else f"{anomaly.delta_ratio * 100:+.1f}%"
    return (
        f"anomaly   : at={anomaly.timestamp_sec:.2f}s {anomaly.metric} {anomaly.kind} "
        f"baseline={baseline} current={current} delta={delta}"
    )


def _format_anomaly_value(metric: str, value: float) -> str:
    if metric.endswith("-rate"):
        return f"{value * 100:.2f}%"
    return _format_value(value)


def _render_insight(insight: ExpertInsight) -> list[str]:
    lines = [f"insight   : {insight.headline}; {insight.detail}"]
    if insight.recommendation:
        lines.append(f"next-step : {insight.recommendation}")
    return lines


def _latest_anomaly(
    anomalies: tuple[ObservationAnomaly, ...],
    *,
    metric: str,
    kind: str,
) -> ObservationAnomaly | None:
    for anomaly in reversed(anomalies):
        if anomaly.metric == metric and anomaly.kind == kind:
            return anomaly
    return None


def _top_items(counter: Counter[str], limit: int) -> tuple[tuple[str, int], ...]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return tuple(items[:limit])


def _thread_key(record: PerfScriptRecord) -> str:
    return f"{record.comm} pid={record.pid} tid={record.tid}"


def _callchain_key(callchain: tuple[str, ...]) -> str:
    return " <- ".join(callchain[:6])


def _render_frame(symbol: str | None, dso: str | None) -> str:
    if symbol is None:
        return "<unknown>"
    if dso is None:
        return symbol
    return f"{symbol} [{dso}]"


def _symbol_key(record: PerfScriptRecord) -> str:
    return _render_frame(record.symbol, record.dso)


def _annotation_symbol(symbol: str) -> str:
    if " [" not in symbol:
        return symbol
    return symbol.rsplit(" [", 1)[0]