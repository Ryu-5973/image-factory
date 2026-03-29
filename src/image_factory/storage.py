from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from image_factory.models import BatchRecord, TaskRecord, TaskSeed, TaskStatus, utc_now_iso


class SqliteStorage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.init_schema()

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                source_path TEXT NOT NULL,
                total_tasks INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                input_index INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                params_json TEXT NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                remote_task_id TEXT,
                remote_metadata_json TEXT NOT NULL DEFAULT '{}',
                result_path TEXT,
                error_code TEXT,
                error_message TEXT,
                next_poll_at TEXT,
                next_retry_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_batch_status ON tasks(batch_id, status);
            CREATE INDEX IF NOT EXISTS idx_tasks_next_poll_at ON tasks(next_poll_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_next_retry_at ON tasks(next_retry_at);
            """
        )
        self.connection.commit()

    def create_batch(
        self,
        *,
        name: str | None,
        provider: str,
        source_path: str,
        tasks: Iterable[TaskSeed],
    ) -> BatchRecord:
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        created_at = utc_now_iso()
        task_list = list(tasks)
        batch_name = name or batch_id

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO batches (id, name, provider, source_path, total_tasks, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (batch_id, batch_name, provider, source_path, len(task_list), created_at, created_at),
            )
            self.connection.executemany(
                """
                INSERT INTO tasks (
                    batch_id, input_index, prompt, params_json, provider, status,
                    attempt, remote_metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, '{}', ?, ?)
                """,
                [
                    (
                        batch_id,
                        index,
                        task.prompt,
                        json.dumps(task.params, ensure_ascii=True, sort_keys=True),
                        provider,
                        TaskStatus.PENDING.value,
                        created_at,
                        created_at,
                    )
                    for index, task in enumerate(task_list)
                ],
            )

        return self.get_batch(batch_id)

    def list_batches(self) -> list[BatchRecord]:
        rows = self.connection.execute("SELECT * FROM batches ORDER BY created_at DESC").fetchall()
        return [self._row_to_batch(row) for row in rows]

    def get_batch(self, batch_id: str) -> BatchRecord:
        row = self.connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown batch: {batch_id}")
        return self._row_to_batch(row)

    def get_task(self, task_id: int) -> TaskRecord:
        row = self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task id: {task_id}")
        return self._row_to_task(row)

    def list_tasks(self, batch_id: str, limit: int = 20) -> list[TaskRecord]:
        rows = self.connection.execute(
            "SELECT * FROM tasks WHERE batch_id = ? ORDER BY id LIMIT ?",
            (batch_id, limit),
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def promote_ready_tasks(self) -> int:
        now = utc_now_iso()
        with self.connection:
            promoted = self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, next_retry_at = NULL
                WHERE status = ?
                   OR (status = ? AND next_retry_at IS NOT NULL AND next_retry_at <= ?)
                """,
                (
                    TaskStatus.READY.value,
                    now,
                    TaskStatus.PENDING.value,
                    TaskStatus.RETRY_WAITING.value,
                    now,
                ),
            ).rowcount
        return promoted

    def reset_submitting_tasks(self, provider: str | None = None, batch_id: str | None = None) -> int:
        now = utc_now_iso()
        with self.connection:
            reset = self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?
                WHERE status = ?
                  AND (? IS NULL OR provider = ?)
                  AND (? IS NULL OR batch_id = ?)
                """,
                (
                    TaskStatus.READY.value,
                    now,
                    TaskStatus.SUBMITTING.value,
                    provider,
                    provider,
                    batch_id,
                    batch_id,
                ),
            ).rowcount
        return reset

    def claim_ready_tasks(
        self,
        limit: int,
        provider: str | None = None,
        batch_id: str | None = None,
    ) -> list[TaskRecord]:
        now = utc_now_iso()
        return self._claim_tasks(
            query="""
                SELECT id
                FROM tasks
                WHERE status = ?
                  AND (? IS NULL OR provider = ?)
                  AND (? IS NULL OR batch_id = ?)
                ORDER BY id
                LIMIT ?
            """,
            query_params=(TaskStatus.READY.value, provider, provider, batch_id, batch_id, limit),
            update_status=TaskStatus.SUBMITTING,
            updated_at=now,
            increment_attempt=True,
        )

    def claim_polling_tasks(self, limit: int, provider: str | None = None) -> list[TaskRecord]:
        now = utc_now_iso()
        rows = self.connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE status = ?
              AND next_poll_at IS NOT NULL
              AND next_poll_at <= ?
              AND (? IS NULL OR provider = ?)
            ORDER BY next_poll_at, id
            LIMIT ?
            """,
            (TaskStatus.POLLING.value, now, provider, provider, limit),
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def claim_download_tasks(self, limit: int, provider: str | None = None) -> list[TaskRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE status = ?
              AND (? IS NULL OR provider = ?)
            ORDER BY updated_at, id
            LIMIT ?
            """,
            (TaskStatus.DOWNLOADING.value, provider, provider, limit),
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def set_task_polling(
        self,
        task_id: int,
        *,
        remote_task_id: str,
        remote_metadata: dict,
        next_poll_at: str,
    ) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, remote_task_id = ?, remote_metadata_json = ?, next_poll_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.POLLING.value,
                    remote_task_id,
                    json.dumps(remote_metadata, ensure_ascii=True, sort_keys=True),
                    next_poll_at,
                    now,
                    task_id,
                ),
            )

    def reschedule_poll(self, task_id: int, *, remote_metadata: dict, next_poll_at: str) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE tasks
                SET remote_metadata_json = ?, next_poll_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(remote_metadata, ensure_ascii=True, sort_keys=True), next_poll_at, now, task_id),
            )

    def set_task_downloading(self, task_id: int, *, remote_metadata: dict) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, remote_metadata_json = ?, next_poll_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.DOWNLOADING.value,
                    json.dumps(remote_metadata, ensure_ascii=True, sort_keys=True),
                    now,
                    task_id,
                ),
            )

    def mark_task_success(self, task_id: int, *, result_path: str, remote_metadata: dict) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, result_path = ?, remote_metadata_json = ?, error_code = NULL,
                    error_message = NULL, next_poll_at = NULL, next_retry_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.SUCCEEDED.value,
                    result_path,
                    json.dumps(remote_metadata, ensure_ascii=True, sort_keys=True),
                    now,
                    now,
                    task_id,
                ),
            )

    def mark_task_retry(self, task_id: int, *, error_code: str, error_message: str, next_retry_at: str) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, error_code = ?, error_message = ?, next_poll_at = NULL,
                    next_retry_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.RETRY_WAITING.value,
                    error_code,
                    error_message,
                    next_retry_at,
                    now,
                    task_id,
                ),
            )

    def mark_task_failure(
        self,
        task_id: int,
        *,
        status: TaskStatus,
        error_code: str,
        error_message: str,
    ) -> None:
        now = utc_now_iso()
        with self.connection:
            self.connection.execute(
                """
                UPDATE tasks
                SET status = ?, error_code = ?, error_message = ?, next_poll_at = NULL,
                    next_retry_at = NULL, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (status.value, error_code, error_message, now, now, task_id),
            )

    def aggregate_counts(self, batch_id: str) -> dict[str, int]:
        rows = self.connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM tasks
            WHERE batch_id = ?
            GROUP BY status
            """,
            (batch_id,),
        ).fetchall()
        counts = defaultdict(int)
        for row in rows:
            counts[row["status"]] = row["count"]
        return dict(counts)

    def count_active_tasks(self, batch_id: str | None = None) -> int:
        terminal = tuple(status.value for status in TaskStatus.terminal())
        placeholders = ",".join("?" for _ in terminal)
        if batch_id:
            row = self.connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM tasks
                WHERE batch_id = ?
                  AND status NOT IN ({placeholders})
                """,
                (batch_id, *terminal),
            ).fetchone()
        else:
            row = self.connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM tasks
                WHERE status NOT IN ({placeholders})
                """,
                terminal,
            ).fetchone()
        return int(row["count"])

    def next_due_at(self, provider: str | None = None, batch_id: str | None = None) -> str | None:
        clauses = []
        params: list[object] = []
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if batch_id:
            clauses.append("batch_id = ?")
            params.append(batch_id)

        where = " AND ".join(clauses)
        where_sql = f"AND {where}" if where else ""
        row = self.connection.execute(
            f"""
            SELECT MIN(due_at) AS due_at
            FROM (
                SELECT next_poll_at AS due_at
                FROM tasks
                WHERE status = ? AND next_poll_at IS NOT NULL {where_sql}
                UNION ALL
                SELECT next_retry_at AS due_at
                FROM tasks
                WHERE status = ? AND next_retry_at IS NOT NULL {where_sql}
            )
            """,
            (
                TaskStatus.POLLING.value,
                *params,
                TaskStatus.RETRY_WAITING.value,
                *params,
            ),
        ).fetchone()
        return row["due_at"] if row else None

    def _claim_tasks(
        self,
        *,
        query: str,
        query_params: tuple[object, ...],
        update_status: TaskStatus,
        updated_at: str,
        increment_attempt: bool,
    ) -> list[TaskRecord]:
        with self.connection:
            task_rows = self.connection.execute(query, query_params).fetchall()
            ids = [row["id"] for row in task_rows]
            if not ids:
                return []
            attempt_sql = ", attempt = attempt + 1" if increment_attempt else ""
            placeholders = ",".join("?" for _ in ids)
            self.connection.execute(
                f"""
                UPDATE tasks
                SET status = ?, updated_at = ?{attempt_sql}
                WHERE id IN ({placeholders})
                """,
                (update_status.value, updated_at, *ids),
            )
        return [self.get_task(task_id) for task_id in ids]

    @staticmethod
    def _row_to_batch(row: sqlite3.Row) -> BatchRecord:
        return BatchRecord(
            id=row["id"],
            name=row["name"],
            provider=row["provider"],
            source_path=row["source_path"],
            total_tasks=row["total_tasks"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            input_index=row["input_index"],
            prompt=row["prompt"],
            params=json.loads(row["params_json"]),
            provider=row["provider"],
            status=TaskStatus(row["status"]),
            attempt=row["attempt"],
            remote_task_id=row["remote_task_id"],
            remote_metadata=json.loads(row["remote_metadata_json"] or "{}"),
            result_path=row["result_path"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            next_poll_at=row["next_poll_at"],
            next_retry_at=row["next_retry_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )
