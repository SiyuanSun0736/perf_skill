from __future__ import annotations

import csv
import datetime as dt
from io import StringIO
from pathlib import Path

from perf_skill.models import ObservationRequest, PerfSample, PerfStatError, TargetProcess

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
    plt, line2d, ticker = _load_plotting()
    series = _collect_series(request, samples)

    if not series:
        figure = _build_empty_figure(plt, target)
        return _figure_to_svg(figure, plt, show_legend=show_legend)

    figure = _build_timeline_figure(
        plt,
        line2d,
        ticker,
        request,
        target,
        series,
        show_legend=show_legend,
    )
    return _figure_to_svg(figure, plt, show_legend=show_legend)


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


def _build_empty_figure(plt, target: TargetProcess):
    figure = plt.figure(figsize=(13.5, 2.6), facecolor="#f8fafc")
    figure.text(
        0.06,
        0.72,
        f"perf-skill timeline for pid={target.pid} comm={target.comm}",
        ha="left",
        va="center",
        fontsize=18,
        fontweight="bold",
        color="#0f172a",
    )
    figure.text(
        0.06,
        0.42,
        "No samples were captured, so no timeline could be drawn.",
        ha="left",
        va="center",
        fontsize=12,
        color="#64748b",
    )
    return figure


def _build_timeline_figure(
    plt,
    line2d,
    ticker,
    request: ObservationRequest,
    target: TargetProcess,
    series: list[tuple[str, list[tuple[float, float]]]],
    *,
    show_legend: bool,
):
    subplot_count = len(series)
    figure_height = max(4.4, 1.95 * subplot_count + 1.8)
    figure, axes = plt.subplots(
        subplot_count,
        1,
        sharex=True,
        figsize=(13.5, figure_height),
    )
    figure.patch.set_facecolor("#f8fafc")
    axes_list = _normalize_axes(axes)

    legend_rows = 1 + (max(0, len(series) - 1) // 4) if show_legend else 0
    top_margin = 0.90 - 0.045 * max(0, legend_rows - 1)
    if show_legend:
        top_margin -= 0.035
    top_margin = max(0.72, top_margin)

    figure.subplots_adjust(
        left=0.10,
        right=0.98,
        bottom=0.08,
        top=top_margin,
        hspace=0.62,
    )
    figure.suptitle(
        f"perf-skill timeline for pid={target.pid} comm={target.comm}",
        x=0.10,
        y=0.985,
        ha="left",
        va="top",
        fontsize=18,
        fontweight="bold",
        color="#0f172a",
    )
    figure.text(
        0.10,
        0.955,
        f"events: {', '.join(request.events)}",
        ha="left",
        va="top",
        fontsize=10,
        color="#475569",
    )

    start_time = series[0][1][0][0]
    end_time = max(points[-1][0] for _, points in series)
    time_span = max(end_time - start_time, request.interval_ms / 1000.0, 1e-9)

    legend_handles = []
    legend_labels = []
    for index, ((name, points), axis) in enumerate(zip(series, axes_list, strict=False)):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        legend_handles.append(
            line2d(
                [0],
                [0],
                color=color,
                linewidth=2.4,
                marker="o",
                markersize=5.2,
                markerfacecolor="#ffffff",
                markeredgewidth=1.4,
            )
        )
        legend_labels.append(name)
        _style_axis(axis)
        _plot_series_on_axis(
            axis,
            ticker,
            name=name,
            points=points,
            color=color,
            start_time=start_time,
            time_span=time_span,
        )

    if show_legend:
        legend = figure.legend(
            legend_handles,
            legend_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.935),
            ncol=min(4, len(legend_labels)),
            frameon=False,
            fontsize=9,
            handlelength=2.6,
            columnspacing=1.4,
        )
        legend.set_gid("legend")

    axes_list[-1].set_xlim(0.0, time_span)
    axes_list[-1].set_xlabel(
        f"Seconds since first sample (interval={request.interval_ms}ms)",
        fontsize=10,
        color="#64748b",
        labelpad=10,
    )
    return figure


def _normalize_axes(axes) -> list:
    try:
        return list(axes.flat)
    except AttributeError:
        return [axes]


def _style_axis(axis) -> None:
    axis.set_facecolor("#ffffff")
    axis.grid(True, axis="y", color="#e2e8f0", linewidth=0.9)
    axis.grid(False, axis="x")
    for spine in axis.spines.values():
        spine.set_color("#cbd5e1")
        spine.set_linewidth(1.0)
    axis.tick_params(axis="x", colors="#64748b", labelsize=9)
    axis.tick_params(axis="y", colors="#475569", labelsize=9)


def _plot_series_on_axis(
    axis,
    ticker,
    *,
    name: str,
    points: list[tuple[float, float]],
    color: str,
    start_time: float,
    time_span: float,
) -> None:
    xs = [timestamp - start_time for timestamp, _ in points]
    ys = [value for _, value in points]

    if len(xs) == 1:
        x_center = time_span / 2.0
        xs = [x_center]

    axis.plot(
        xs,
        ys,
        color=color,
        linewidth=2.4,
        solid_capstyle="round",
        marker="o",
        markersize=5.0,
        markerfacecolor="#ffffff",
        markeredgewidth=1.4,
        markeredgecolor=color,
        zorder=3,
    )
    axis.fill_between(xs, ys, [min(ys)] * len(ys), color=color, alpha=0.08, zorder=2)
    axis.set_title(
        name,
        loc="left",
        fontsize=12,
        fontweight="bold",
        color="#0f172a",
        pad=12,
    )
    axis.text(
        1.0,
        1.08,
        f"min={_format_number(min(ys))}   max={_format_number(max(ys))}   last={_format_number(ys[-1])}",
        transform=axis.transAxes,
        ha="right",
        va="center",
        fontsize=9,
        color="#64748b",
    )
    axis.yaxis.set_major_formatter(ticker.FuncFormatter(_format_axis_tick))
    axis.xaxis.set_major_formatter(ticker.FuncFormatter(_format_time_tick))


def _figure_to_svg(figure, plt, *, show_legend: bool) -> str:
    output = StringIO()
    try:
        figure.savefig(
            output,
            format="svg",
            facecolor=figure.get_facecolor(),
            bbox_inches="tight",
            pad_inches=0.18,
        )
        return _annotate_svg(output.getvalue(), show_legend=show_legend)
    finally:
        plt.close(figure)


def _annotate_svg(svg_text: str, *, show_legend: bool) -> str:
    legend_state = "on" if show_legend else "off"
    marker = (
        "<!-- perf-skill-renderer:matplotlib -->\n"
        f"<!-- perf-skill-legend:{legend_state} -->\n<svg "
    )
    return svg_text.replace("<svg ", marker, 1)


def _load_plotting():
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib import ticker
    except ModuleNotFoundError as error:
        raise PerfStatError(
            "SVG export requires matplotlib; install the package dependencies first",
        ) from error
    return plt, Line2D, ticker


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    return f"{value:.3f}"


def _format_axis_tick(value: float, _position: float) -> str:
    return _format_number(value)


def _format_time_tick(value: float, _position: float) -> str:
    return f"{value:.2f}s"