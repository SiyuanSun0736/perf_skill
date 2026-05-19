from __future__ import annotations

import datetime as dt
import os
import sys
from collections import deque

from perf_skill.models import ObservationRequest, PerfSample, TargetProcess

SPARKLINE_LEVELS = " .:-=+*#%@"


class DashboardRenderer:
    def __init__(self, request: ObservationRequest, target: TargetProcess, *, plain_output: bool) -> None:
        self.request = request
        self.target = target
        self.plain_output = plain_output
        self.history: dict[str, deque[float]] = {
            event: deque(maxlen=request.history_size) for event in request.events
        }
        self.history["ipc"] = deque(maxlen=request.history_size)

    def render(self, sample: PerfSample) -> None:
        for event in self.request.events:
            value = sample.values.get(event)
            if value is not None:
                self.history[event].append(value)
        if sample.ipc is not None:
            self.history["ipc"].append(sample.ipc)

        if self.plain_output or not sys.stdout.isatty():
            sys.stdout.write(self._render_plain(sample) + "\n")
            sys.stdout.flush()
            return

        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write(self._render_dashboard(sample))
        sys.stdout.flush()

    def _render_plain(self, sample: PerfSample) -> str:
        timestamp = _format_timestamp(sample.timestamp_sec)
        metrics = [
            f"{event}={_format_count(sample.values.get(event))}"
            for event in self.request.events
            if event in sample.values
        ]
        if sample.ipc is not None:
            metrics.append(f"ipc={sample.ipc:.2f}")
        return f"[{timestamp}] pid={self.target.pid} comm={self.target.comm} " + " ".join(metrics)

    def _render_dashboard(self, sample: PerfSample) -> str:
        lines = [
            "perf-skill hardware event observe",
            f"target   : pid={self.target.pid} comm={self.target.comm}",
            f"interval : {self.request.interval_ms} ms",
            f"events   : {', '.join(self.request.events)}",
            f"sample   : {_format_timestamp(sample.timestamp_sec)}",
            "",
            "current",
        ]

        for event in self.request.events:
            if event in sample.values:
                lines.append(f"  {event:<16} {_format_count(sample.values[event])}")
        if sample.ipc is not None:
            lines.append(f"  {'ipc':<16} {sample.ipc:.3f}")

        lines.extend([
            "",
            "history",
        ])

        for key in list(self.request.events) + ["ipc"]:
            values = list(self.history[key])
            if not values:
                continue
            suffix = f" last={_format_count(values[-1])}" if key != "ipc" else f" last={values[-1]:.3f}"
            lines.append(f"  {key:<16} {_sparkline(values)}{suffix}")

        lines.extend([
            "",
            "Ctrl-C to stop.",
        ])
        return os.linesep.join(lines) + os.linesep


def _sparkline(values: list[float]) -> str:
    if len(values) == 1:
        return SPARKLINE_LEVELS[-1]
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return SPARKLINE_LEVELS[-2] * len(values)
    result = []
    levels = len(SPARKLINE_LEVELS) - 1
    for value in values:
        position = round((value - minimum) / (maximum - minimum) * levels)
        result.append(SPARKLINE_LEVELS[position])
    return "".join(result)


def _format_count(value: float | None) -> str:
    if value is None:
        return "n/a"
    suffixes = ["", "K", "M", "G", "T"]
    scaled = float(value)
    suffix_index = 0
    while abs(scaled) >= 1000 and suffix_index < len(suffixes) - 1:
        scaled /= 1000.0
        suffix_index += 1
    if suffix_index == 0:
        return f"{scaled:.0f}"
    return f"{scaled:.2f}{suffixes[suffix_index]}"


def _format_timestamp(timestamp_sec: float) -> str:
    return dt.datetime.fromtimestamp(timestamp_sec).strftime("%H:%M:%S")
