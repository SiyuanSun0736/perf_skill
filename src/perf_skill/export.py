from __future__ import annotations

import csv
import datetime as dt
import html
from pathlib import Path

from perf_skill.models import ObservationRequest, PerfSample, TargetProcess

SERIES_COLORS = (
    "#155e75",
    "#b45309",
    "#15803d",
    "#b91c1c",
    "#4338ca",
    "#0f766e",
)


class CsvSampleWriter:
    def __init__(
        self,
        output_path: str,
        request: ObservationRequest,
        target: TargetProcess,
    ) -> None:
        self.request = request
        self.target = target
        self.path = Path(output_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=[
                "timestamp_sec",
                "timestamp_iso",
                "pid",
                "comm",
                *request.events,
                "ipc",
            ],
        )
        self.writer.writeheader()

    def write(self, sample: PerfSample) -> None:
        row: dict[str, str] = {
            "timestamp_sec": f"{sample.timestamp_sec:.6f}",
            "timestamp_iso": dt.datetime.fromtimestamp(sample.timestamp_sec).isoformat(),
            "pid": str(self.target.pid),
            "comm": self.target.comm,
            "ipc": _format_optional_number(sample.ipc),
        }
        for event in self.request.events:
            row[event] = _format_optional_number(sample.values.get(event))
        self.writer.writerow(row)
        self.file.flush()

    def close(self) -> None:
        self.file.close()


def write_svg_report(
    output_path: str,
    request: ObservationRequest,
    target: TargetProcess,
    samples: list[PerfSample],
    *,
    show_legend: bool = True,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_svg_report(request, target, samples, show_legend=show_legend), encoding="utf-8")


def render_svg_report(
    request: ObservationRequest,
    target: TargetProcess,
    samples: list[PerfSample],
    *,
    show_legend: bool = True,
) -> str:
    width = 1200
    margin_left = 84
    margin_right = 28
    margin_top = 56
    panel_height = 140
    panel_gap = 28
    plot_width = width - margin_left - margin_right
    series = _collect_series(request, samples)

    if not series:
        return _render_empty_svg(width, target)

    legend_height = 0
    legend_top = margin_top + 16
    if show_legend:
        legend_height = _estimate_legend_height(series, width, margin_left)
        margin_top += legend_height

    height = margin_top + len(series) * panel_height + (len(series) - 1) * panel_gap + 40
    start_time = samples[0].timestamp_sec
    end_time = samples[-1].timestamp_sec
    time_span = max(end_time - start_time, 1e-9)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="{margin_left}" y="32" font-size="22" font-family="monospace" fill="#0f172a">perf-skill timeline for pid={target.pid} comm={html.escape(target.comm)}</text>',
        f'<text x="{margin_left}" y="50" font-size="12" font-family="monospace" fill="#475569">events: {html.escape(", ".join(request.events))}</text>',
    ]

    if show_legend:
        lines.extend(_render_legend(series, left=margin_left, top=legend_top, width=width))

    for index, (name, points) in enumerate(series):
        top = margin_top + index * (panel_height + panel_gap)
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        values = [value for _, value in points]
        minimum = min(values)
        maximum = max(values)
        if minimum == maximum:
            minimum = 0.0 if minimum >= 0 else minimum * 1.1
            maximum = maximum + 1.0 if maximum == 0 else maximum * 1.1

        lines.extend(_render_series_panel(
            name=name,
            points=points,
            color=color,
            top=top,
            left=margin_left,
            plot_width=plot_width,
            panel_height=panel_height,
            start_time=start_time,
            time_span=time_span,
            minimum=minimum,
            maximum=maximum,
            width=width,
        ))

    footer_y = height - 12
    lines.append(
        f'<text x="{margin_left}" y="{footer_y}" font-size="12" font-family="monospace" fill="#64748b">x-axis: seconds since first sample, interval={request.interval_ms}ms</text>'
    )
    lines.append('</svg>')
    return "\n".join(lines)


def _collect_series(
    request: ObservationRequest,
    samples: list[PerfSample],
) -> list[tuple[str, list[tuple[float, float]]]]:
    series: list[tuple[str, list[tuple[float, float]]]] = []
    for event in request.events:
        points = [
            (sample.timestamp_sec, sample.values[event])
            for sample in samples
            if event in sample.values
        ]
        if points:
            series.append((event, points))

    ipc_points = [
        (sample.timestamp_sec, sample.ipc)
        for sample in samples
        if sample.ipc is not None
    ]
    if ipc_points:
        series.append(("ipc", [(timestamp, value) for timestamp, value in ipc_points if value is not None]))
    return series


def _render_empty_svg(width: int, target: TargetProcess) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="180" viewBox="0 0 {width} 180">',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="64" y="72" font-size="22" font-family="monospace" fill="#0f172a">perf-skill timeline for pid={target.pid} comm={html.escape(target.comm)}</text>',
        '<text x="64" y="108" font-size="14" font-family="monospace" fill="#64748b">No samples were captured, so no timeline could be drawn.</text>',
        '</svg>',
    ])


def _render_legend(
    series: list[tuple[str, list[tuple[float, float]]]],
    *,
    left: int,
    top: int,
    width: int,
) -> list[str]:
    lines = ['<g id="legend">']
    x = left
    y = top
    max_x = width - 64
    line_height = 20

    for index, (name, _) in enumerate(series):
        label_width = 28 + max(56, len(name) * 8)
        if x + label_width > max_x:
            x = left
            y += line_height
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        lines.append(f'<rect x="{x}" y="{y - 10}" width="12" height="12" rx="3" fill="{color}" />')
        lines.append(
            f'<text x="{x + 18}" y="{y}" font-size="12" font-family="monospace" fill="#334155">{html.escape(name)}</text>'
        )
        x += label_width

    lines.append('</g>')
    return lines


def _estimate_legend_height(
    series: list[tuple[str, list[tuple[float, float]]]],
    width: int,
    left: int,
) -> int:
    x = left
    y = 0
    max_x = width - 64
    line_height = 20
    for name, _ in series:
        label_width = 28 + max(56, len(name) * 8)
        if x + label_width > max_x:
            x = left
            y += line_height
        x += label_width
    return 24 + y


def _render_series_panel(
    *,
    name: str,
    points: list[tuple[float, float]],
    color: str,
    top: int,
    left: int,
    plot_width: int,
    panel_height: int,
    start_time: float,
    time_span: float,
    minimum: float,
    maximum: float,
    width: int,
) -> list[str]:
    lines = [
        f'<rect x="{left}" y="{top}" width="{plot_width}" height="{panel_height}" rx="12" fill="#ffffff" stroke="#cbd5e1" />',
        f'<text x="{left + 12}" y="{top + 20}" font-size="14" font-family="monospace" fill="#0f172a">{html.escape(name)}</text>',
        f'<text x="{left + 12}" y="{top + 38}" font-size="11" font-family="monospace" fill="#64748b">min={_format_number(minimum)} max={_format_number(maximum)} last={_format_number(points[-1][1])}</text>',
    ]

    for step in range(3):
        y = top + 20 + step * ((panel_height - 32) / 2)
        lines.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" stroke="#e2e8f0" stroke-width="1" />'
        )

    polyline_points = []
    for timestamp, value in points:
        x = _scale_x(timestamp, start_time, time_span, left, plot_width)
        y = _scale_y(value, top, panel_height, minimum, maximum)
        polyline_points.append(f"{x:.1f},{y:.1f}")

    if len(polyline_points) >= 2:
        lines.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{" ".join(polyline_points)}" />'
        )
    if polyline_points:
        last_x, last_y = polyline_points[-1].split(",")
        lines.append(f'<circle cx="{last_x}" cy="{last_y}" r="3.5" fill="{color}" />')

    lines.append(
        f'<text x="{left}" y="{top + panel_height + 16}" font-size="10" font-family="monospace" fill="#94a3b8">0.0s</text>'
    )
    lines.append(
        f'<text x="{width - 78}" y="{top + panel_height + 16}" font-size="10" font-family="monospace" fill="#94a3b8">{time_span:.2f}s</text>'
    )
    return lines


def _scale_x(timestamp: float, start_time: float, time_span: float, left: int, plot_width: int) -> float:
    if time_span <= 1e-9:
        return left + plot_width / 2
    return left + ((timestamp - start_time) / time_span) * plot_width


def _scale_y(value: float, top: int, panel_height: int, minimum: float, maximum: float) -> float:
    plot_top = top + 18
    plot_height = panel_height - 34
    if maximum == minimum:
        return plot_top + plot_height / 2
    ratio = (value - minimum) / (maximum - minimum)
    return plot_top + (1 - ratio) * plot_height


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    return f"{value:.3f}"