from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta

from image_factory.models import FetchResult, PollResult, RemoteTaskState, SubmissionResult, TaskRecord, utc_now
from image_factory.providers.base import ImageProvider, ProviderFatalError, ProviderRetryableError

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+tH9QAAAAASUVORK5CYII="
)


class MockImageProvider(ImageProvider):
    name = "mock"

    def submit(self, task: TaskRecord) -> SubmissionResult:
        retry_until_attempt = int(task.params.get("retry_until_attempt", 0) or 0)
        if task.attempt <= retry_until_attempt:
            raise ProviderRetryableError("mock_retryable", "Simulated transient submit failure")
        if task.params.get("force_fatal_submit_error"):
            raise ProviderFatalError("mock_fatal", "Simulated fatal submit failure")

        ready_after = float(task.params.get("ready_after_seconds", 0.0) or 0.0)
        remote_metadata = {
            "ready_at": (utc_now() + timedelta(seconds=ready_after)).isoformat(),
            "seed": task.params.get("seed", task.id * 17),
            "prompt": task.prompt,
        }
        return SubmissionResult(
            remote_task_id=f"mock-{uuid.uuid4().hex}",
            remote_metadata=remote_metadata,
            poll_after_seconds=float(task.params.get("poll_after_seconds", 0.0) or 0.0),
        )

    def poll(self, task: TaskRecord) -> PollResult:
        if task.params.get("force_remote_failure"):
            return PollResult(
                state=RemoteTaskState.FAILED,
                error_code="mock_remote_failure",
                error_message="Simulated remote task failure",
            )

        ready_at = task.remote_metadata.get("ready_at")
        if not ready_at:
            raise ProviderFatalError("mock_bad_state", "Missing ready_at in remote metadata")

        if utc_now() >= datetime.fromisoformat(ready_at):
            return PollResult(
                state=RemoteTaskState.SUCCEEDED,
                remote_metadata=task.remote_metadata,
            )
        return PollResult(
            state=RemoteTaskState.RUNNING,
            remote_metadata=task.remote_metadata,
            poll_after_seconds=float(task.params.get("poll_after_seconds", 1.0) or 1.0),
        )

    def fetch_result(self, task: TaskRecord) -> FetchResult:
        if task.params.get("force_download_retryable_error"):
            raise ProviderRetryableError("mock_download_retry", "Simulated download retryable failure")
        if task.params.get("force_download_fatal_error"):
            raise ProviderFatalError("mock_download_fatal", "Simulated download fatal failure")

        metadata = dict(task.remote_metadata)
        metadata["provider"] = self.name
        return FetchResult(content=_TINY_PNG, file_extension="png", metadata=metadata)
