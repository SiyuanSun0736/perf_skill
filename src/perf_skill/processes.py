from __future__ import annotations

from pathlib import Path

from perf_skill.models import ObservationError, ObservationRequest, TargetProcess


def resolve_target(
    request: ObservationRequest,
    *,
    proc_root: Path = Path("/proc"),
) -> TargetProcess:
    if request.pid is not None:
        target = _resolve_pid(request.pid, proc_root=proc_root)
        if request.comm is not None and target.comm != request.comm:
            raise ObservationError(
                f"pid {request.pid} resolved to comm={target.comm}, not {request.comm}"
            )
        return target

    if request.comm is None:
        raise ObservationError("missing target: specify pid, comm, or both")

    matches = [process for process in iter_processes(proc_root=proc_root) if process.comm == request.comm]
    if not matches:
        raise ObservationError(f"no process found for comm={request.comm}")
    if len(matches) > 1:
        options = ", ".join(str(process.pid) for process in matches[:8])
        raise ObservationError(
            f"comm={request.comm} matched multiple pids: {options}; specify pid"
        )
    return matches[0]


def iter_processes(*, proc_root: Path = Path("/proc")) -> list[TargetProcess]:
    processes: list[TargetProcess] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if not comm:
            continue
        processes.append(TargetProcess(pid=int(entry.name), comm=comm))
    processes.sort(key=lambda process: process.pid)
    return processes


def _resolve_pid(pid: int, *, proc_root: Path) -> TargetProcess:
    comm_path = proc_root / str(pid) / "comm"
    if not comm_path.exists():
        raise ObservationError(f"pid {pid} does not exist")
    try:
        comm = comm_path.read_text(encoding="utf-8").strip()
    except PermissionError as error:
        raise ObservationError(f"cannot read /proc/{pid}/comm: {error}") from error
    return TargetProcess(pid=pid, comm=comm)
