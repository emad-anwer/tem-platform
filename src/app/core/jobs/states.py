from enum import StrEnum


class ScanRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


TERMINAL_STATUSES = {ScanRunStatus.SUCCEEDED, ScanRunStatus.FAILED}
_ALLOWED_TRANSITIONS = {
    ScanRunStatus.QUEUED: {ScanRunStatus.RUNNING},
    ScanRunStatus.RUNNING: {ScanRunStatus.SUCCEEDED, ScanRunStatus.FAILED},
    ScanRunStatus.SUCCEEDED: set(),
    ScanRunStatus.FAILED: set(),
}


def transition_status(current: str, target: ScanRunStatus) -> None:
    """Raise when a scan run state change is not allowed."""
    try:
        current_status = ScanRunStatus(current)
    except ValueError as exc:
        raise ValueError(f"Unknown scan run status: {current}") from exc
    if target not in _ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"Cannot transition scan run from {current} to {target}.")
