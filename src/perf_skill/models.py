from __future__ import annotations

from dataclasses import dataclass


class ObservationError(ValueError):
    """Raised when the user request cannot be resolved into a valid observation."""


class PerfStatError(RuntimeError):
    """Raised when perf cannot be started or its output cannot be consumed."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "generic",
        diagnostics: tuple[str, ...] = (),
        unsupported_events: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.diagnostics = diagnostics
        self.unsupported_events = dict(unsupported_events or {})


@dataclass(frozen=True)
class ObservationRequest:
    statement: str
    pid: int | None
    comm: str | None
    events: tuple[str, ...]
    interval_ms: int
    history_size: int


@dataclass(frozen=True)
class TargetProcess:
    pid: int
    comm: str


@dataclass(frozen=True)
class PerfMeasurement:
    timestamp_sec: float
    event: str
    value: float


@dataclass(frozen=True)
class PerfSample:
    timestamp_sec: float
    values: dict[str, float]
    ipc: float | None
