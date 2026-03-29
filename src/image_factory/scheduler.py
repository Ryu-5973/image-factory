from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from image_factory.config import RuntimeSettings
from image_factory.models import RemoteTaskState, TaskRecord, TaskStatus, parse_timestamp, utc_now
from image_factory.providers.base import ImageProvider, ProviderFatalError, ProviderRetryableError
from image_factory.rate_limiter import TokenBucket
from image_factory.storage import SqliteStorage


@dataclass(slots=True)
class DrainSummary:
    promoted: int = 0
    submitted: int = 0
    polled: int = 0
    downloaded: int = 0
    retried: int = 0
    failed: int = 0

    @property
    def work_done(self) -> int:
        return self.promoted + self.submitted + self.polled + self.downloaded + self.retried + self.failed


class Scheduler:
    def __init__(
        self,
        *,
        storage: SqliteStorage,
        provider: ImageProvider,
        settings: RuntimeSettings,
    ):
        self.storage = storage
        self.provider = provider
        self.settings = settings
        self.output_dir = Path(settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.submit_limiter = TokenBucket(rate=settings.rate_limits.submit_rpm, per_seconds=60.0)
        self.poll_limiter = TokenBucket(rate=settings.rate_limits.poll_rpm, per_seconds=60.0)
        self.download_limiter = TokenBucket(rate=settings.rate_limits.download_rpm, per_seconds=60.0)

    def drain_once(self, provider_name: str | None = None) -> DrainSummary:
        summary = DrainSummary()
        summary.promoted = self.storage.promote_ready_tasks()

        submit_budget = self.settings.rate_limits.submit_batch_size
        while submit_budget > 0 and self.submit_limiter.allow():
            submit_tasks = self.storage.claim_ready_tasks(1, provider=provider_name)
            if not submit_tasks:
                break
            self._handle_submit(submit_tasks[0], summary)
            submit_budget -= 1

        poll_tasks = self.storage.claim_polling_tasks(
            self.settings.rate_limits.poll_batch_size,
            provider=provider_name,
        )
        for task in poll_tasks:
            if not self.poll_limiter.allow():
                break
            self._handle_poll(task, summary)

        download_tasks = self.storage.claim_download_tasks(
            self.settings.rate_limits.download_batch_size,
            provider=provider_name,
        )
        for task in download_tasks:
            if not self.download_limiter.allow():
                break
            self._handle_download(task, summary)

        return summary

    def run(self, *, provider_name: str | None = None, max_cycles: int | None = None) -> None:
        cycles = 0
        while True:
            summary = self.drain_once(provider_name=provider_name)
            cycles += 1
            active_tasks = self.storage.count_active_tasks()
            if active_tasks == 0:
                return
            if max_cycles is not None and cycles >= max_cycles:
                return
            if summary.work_done > 0:
                continue

            wait_seconds = self._next_wait_seconds(provider_name=provider_name)
            time.sleep(wait_seconds)

    def _next_wait_seconds(self, provider_name: str | None = None) -> float:
        due_at = self.storage.next_due_at(provider=provider_name)
        default_sleep = self.settings.rate_limits.idle_sleep_seconds
        if not due_at:
            return default_sleep
        due_time = parse_timestamp(due_at)
        if due_time is None:
            return default_sleep
        seconds = max(0.0, (due_time - utc_now()).total_seconds())
        return min(default_sleep, seconds) if seconds > 0 else 0.0

    def _handle_submit(self, task: TaskRecord, summary: DrainSummary) -> None:
        try:
            result = self.provider.submit(task)
        except ProviderRetryableError as exc:
            self._retry_or_dead_letter(task, exc.code, exc.message, summary)
            return
        except ProviderFatalError as exc:
            self.storage.mark_task_failure(
                task.id,
                status=TaskStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            summary.failed += 1
            return

        next_poll_at = (utc_now() + timedelta(seconds=result.poll_after_seconds)).isoformat()
        self.storage.set_task_polling(
            task.id,
            remote_task_id=result.remote_task_id,
            remote_metadata=result.remote_metadata,
            next_poll_at=next_poll_at,
        )
        summary.submitted += 1

    def _handle_poll(self, task: TaskRecord, summary: DrainSummary) -> None:
        try:
            result = self.provider.poll(task)
        except ProviderRetryableError as exc:
            self._retry_or_dead_letter(task, exc.code, exc.message, summary)
            return
        except ProviderFatalError as exc:
            self.storage.mark_task_failure(
                task.id,
                status=TaskStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            summary.failed += 1
            return

        if result.state == RemoteTaskState.RUNNING:
            next_poll_at = (utc_now() + timedelta(seconds=result.poll_after_seconds)).isoformat()
            self.storage.reschedule_poll(
                task.id,
                remote_metadata=result.remote_metadata,
                next_poll_at=next_poll_at,
            )
            summary.polled += 1
            return

        if result.state == RemoteTaskState.FAILED:
            self.storage.mark_task_failure(
                task.id,
                status=TaskStatus.FAILED,
                error_code=result.error_code or "remote_failed",
                error_message=result.error_message or "Remote task failed",
            )
            summary.failed += 1
            return

        self.storage.set_task_downloading(task.id, remote_metadata=result.remote_metadata)
        summary.polled += 1

    def _handle_download(self, task: TaskRecord, summary: DrainSummary) -> None:
        try:
            result = self.provider.fetch_result(task)
        except ProviderRetryableError as exc:
            self._retry_or_dead_letter(task, exc.code, exc.message, summary)
            return
        except ProviderFatalError as exc:
            self.storage.mark_task_failure(
                task.id,
                status=TaskStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
            )
            summary.failed += 1
            return

        task_dir = self.output_dir / task.batch_id
        task_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._result_path(task_dir, task, result.file_extension)
        file_path.write_bytes(result.content)
        metadata = dict(task.remote_metadata)
        metadata.update(result.metadata)
        self.storage.mark_task_success(task.id, result_path=str(file_path), remote_metadata=metadata)
        summary.downloaded += 1

    def _retry_or_dead_letter(self, task: TaskRecord, code: str, message: str, summary: DrainSummary) -> None:
        if task.attempt >= self.settings.retry.max_attempts:
            self.storage.mark_task_failure(
                task.id,
                status=TaskStatus.DEAD_LETTER,
                error_code=code,
                error_message=message,
            )
            summary.failed += 1
            return

        delay_seconds = self.settings.retry.delay_for_attempt(task.attempt)
        next_retry_at = (utc_now() + timedelta(seconds=delay_seconds)).isoformat()
        self.storage.mark_task_retry(
            task.id,
            error_code=code,
            error_message=message,
            next_retry_at=next_retry_at,
        )
        summary.retried += 1

    def _result_path(self, task_dir: Path, task: TaskRecord, file_extension: str) -> Path:
        requested_name = str(task.params.get("filename", "")).strip()
        stem = _sanitize_filename_stem(Path(requested_name).stem) if requested_name else f"task-{task.id:06d}"
        candidate = task_dir / f"{stem}.{file_extension}"
        if not candidate.exists():
            return candidate
        return task_dir / f"{stem}-{task.id:06d}.{file_extension}"


def _sanitize_filename_stem(value: str) -> str:
    sanitized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return sanitized.strip("_") or "image"
