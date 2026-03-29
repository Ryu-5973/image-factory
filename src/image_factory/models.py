from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    SUBMITTING = "submitting"
    POLLING = "polling"
    DOWNLOADING = "downloading"
    RETRY_WAITING = "retry_waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> set["TaskStatus"]:
        return {cls.SUCCEEDED, cls.FAILED, cls.DEAD_LETTER, cls.CANCELLED}


class RemoteTaskState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class TaskSeed:
    prompt: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BatchRecord:
    id: str
    name: str
    provider: str
    source_path: str
    total_tasks: int
    created_at: str
    updated_at: str


@dataclass(slots=True)
class TaskRecord:
    id: int
    batch_id: str
    input_index: int
    prompt: str
    params: dict[str, Any]
    provider: str
    status: TaskStatus
    attempt: int
    remote_task_id: str | None
    remote_metadata: dict[str, Any]
    result_path: str | None
    error_code: str | None
    error_message: str | None
    next_poll_at: str | None
    next_retry_at: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(slots=True)
class SubmissionResult:
    remote_task_id: str
    remote_metadata: dict[str, Any] = field(default_factory=dict)
    poll_after_seconds: float = 1.0


@dataclass(slots=True)
class PollResult:
    state: RemoteTaskState
    remote_metadata: dict[str, Any] = field(default_factory=dict)
    poll_after_seconds: float = 1.0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class FetchResult:
    content: bytes
    file_extension: str = "png"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BatchProgress:
    batch: BatchRecord
    counts: dict[str, int]
    progress_percent: float
    done_tasks: int
    active_tasks: int
    eta_seconds: int | None
