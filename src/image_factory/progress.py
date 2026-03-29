from __future__ import annotations

from datetime import datetime

from image_factory.models import BatchProgress, TaskStatus, parse_timestamp
from image_factory.storage import SqliteStorage


def build_batch_progress(storage: SqliteStorage, batch_id: str) -> BatchProgress:
    batch = storage.get_batch(batch_id)
    counts = storage.aggregate_counts(batch_id)
    done = sum(counts.get(status.value, 0) for status in TaskStatus.terminal())
    active = batch.total_tasks - done
    progress_percent = 0.0
    if batch.total_tasks:
        progress_percent = round((done / batch.total_tasks) * 100, 2)

    eta_seconds = _estimate_eta(batch.created_at, done, batch.total_tasks)
    return BatchProgress(
        batch=batch,
        counts=counts,
        progress_percent=progress_percent,
        done_tasks=done,
        active_tasks=active,
        eta_seconds=eta_seconds,
    )


def _estimate_eta(created_at: str, done: int, total: int) -> int | None:
    if done <= 0 or total <= done:
        return 0 if total == done else None
    created = parse_timestamp(created_at)
    if created is None:
        return None
    elapsed = (datetime.now(created.tzinfo) - created).total_seconds()
    if elapsed <= 0:
        return None
    rate = done / elapsed
    if rate <= 0:
        return None
    remaining = total - done
    return int(remaining / rate)
