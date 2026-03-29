from __future__ import annotations

import argparse
from pathlib import Path

from image_factory.config import RateLimitSettings, RetrySettings, RuntimeSettings
from image_factory.input_loader import load_task_seeds
from image_factory.progress import build_batch_progress
from image_factory.providers import build_provider
from image_factory.scheduler import Scheduler
from image_factory.storage import SqliteStorage


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "create-batch":
        return _create_batch(args)
    if args.command == "run-worker":
        return _run_worker(args)
    if args.command == "list-batches":
        return _list_batches(args)
    if args.command == "status":
        return _status(args)
    if args.command == "list-tasks":
        return _list_tasks(args)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch scheduler for image generation APIs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_batch = subparsers.add_parser("create-batch", help="Create a batch from a local input file")
    create_batch.add_argument("--db", default="data/image_factory.db")
    create_batch.add_argument("--input", required=True)
    create_batch.add_argument("--provider", required=True)
    create_batch.add_argument("--name")

    run_worker = subparsers.add_parser("run-worker", help="Run the local worker loop")
    run_worker.add_argument("--db", default="data/image_factory.db")
    run_worker.add_argument("--output-dir", default="outputs")
    run_worker.add_argument("--provider", required=True)
    run_worker.add_argument("--submit-rpm", type=int, default=60)
    run_worker.add_argument("--poll-rpm", type=int, default=240)
    run_worker.add_argument("--download-rpm", type=int, default=120)
    run_worker.add_argument("--submit-batch-size", type=int, default=10)
    run_worker.add_argument("--poll-batch-size", type=int, default=20)
    run_worker.add_argument("--download-batch-size", type=int, default=20)
    run_worker.add_argument("--idle-sleep-seconds", type=float, default=1.0)
    run_worker.add_argument("--max-attempts", type=int, default=4)
    run_worker.add_argument("--retry-delays", default="15,30,60,180")
    run_worker.add_argument("--max-cycles", type=int)

    list_batches = subparsers.add_parser("list-batches", help="List known batches")
    list_batches.add_argument("--db", default="data/image_factory.db")

    status = subparsers.add_parser("status", help="Show aggregate progress for a batch")
    status.add_argument("--db", default="data/image_factory.db")
    status.add_argument("--batch-id", required=True)

    list_tasks = subparsers.add_parser("list-tasks", help="Show task details for a batch")
    list_tasks.add_argument("--db", default="data/image_factory.db")
    list_tasks.add_argument("--batch-id", required=True)
    list_tasks.add_argument("--limit", type=int, default=20)

    return parser


def _create_batch(args: argparse.Namespace) -> int:
    storage = SqliteStorage(Path(args.db))
    try:
        input_path = Path(args.input)
        tasks = load_task_seeds(input_path)
        batch = storage.create_batch(
            name=args.name,
            provider=args.provider,
            source_path=str(input_path),
            tasks=tasks,
        )
    finally:
        storage.close()

    print(f"created batch {batch.id} provider={batch.provider} total_tasks={batch.total_tasks}")
    return 0


def _run_worker(args: argparse.Namespace) -> int:
    storage = SqliteStorage(Path(args.db))
    try:
        settings = _build_runtime_settings(args)
        scheduler = Scheduler(
            storage=storage,
            provider=build_provider(args.provider),
            settings=settings,
        )
        scheduler.run(provider_name=args.provider, max_cycles=args.max_cycles)
    finally:
        storage.close()

    print("worker stopped")
    return 0


def _list_batches(args: argparse.Namespace) -> int:
    storage = SqliteStorage(Path(args.db))
    try:
        batches = storage.list_batches()
        if not batches:
            print("no batches")
            return 0
        for batch in batches:
            progress = build_batch_progress(storage, batch.id)
            print(
                f"{batch.id} provider={batch.provider} total={batch.total_tasks} "
                f"done={progress.done_tasks} active={progress.active_tasks} "
                f"progress={progress.progress_percent:.2f}%"
            )
    finally:
        storage.close()
    return 0


def _status(args: argparse.Namespace) -> int:
    storage = SqliteStorage(Path(args.db))
    try:
        progress = build_batch_progress(storage, args.batch_id)
    finally:
        storage.close()

    print(f"batch_id={progress.batch.id}")
    print(f"provider={progress.batch.provider}")
    print(f"total={progress.batch.total_tasks}")
    print(f"done={progress.done_tasks}")
    print(f"active={progress.active_tasks}")
    print(f"progress={progress.progress_percent:.2f}%")
    print(f"eta_seconds={progress.eta_seconds}")
    for status, count in sorted(progress.counts.items()):
        print(f"{status}={count}")
    return 0


def _list_tasks(args: argparse.Namespace) -> int:
    storage = SqliteStorage(Path(args.db))
    try:
        tasks = storage.list_tasks(args.batch_id, limit=args.limit)
    finally:
        storage.close()

    if not tasks:
        print("no tasks")
        return 0

    for task in tasks:
        print(
            f"id={task.id} status={task.status.value} attempt={task.attempt} "
            f"prompt={task.prompt!r} result_path={task.result_path!r} error_code={task.error_code!r}"
        )
    return 0


def _build_runtime_settings(args: argparse.Namespace) -> RuntimeSettings:
    retry_delays = tuple(int(value.strip()) for value in args.retry_delays.split(",") if value.strip())
    return RuntimeSettings(
        db_path=Path(args.db),
        output_dir=Path(args.output_dir),
        rate_limits=RateLimitSettings(
            submit_rpm=args.submit_rpm,
            poll_rpm=args.poll_rpm,
            download_rpm=args.download_rpm,
            submit_batch_size=args.submit_batch_size,
            poll_batch_size=args.poll_batch_size,
            download_batch_size=args.download_batch_size,
            idle_sleep_seconds=args.idle_sleep_seconds,
        ),
        retry=RetrySettings(max_attempts=args.max_attempts, backoff_seconds=retry_delays),
    )
