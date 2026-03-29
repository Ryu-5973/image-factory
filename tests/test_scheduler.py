import shutil
import uuid
from pathlib import Path
import unittest

from image_factory.config import RateLimitSettings, RetrySettings, RuntimeSettings
from image_factory.models import TaskSeed
from image_factory.providers.mock import MockImageProvider
from image_factory.scheduler import Scheduler
from image_factory.storage import SqliteStorage


class SchedulerTests(unittest.TestCase):
    def test_scheduler_runs_batch_to_completion(self) -> None:
        root = Path("tests/.tmp") / f"scheduler-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            storage = SqliteStorage(root / "image_factory.db")
            try:
                batch = storage.create_batch(
                    name="demo",
                    provider="mock",
                    source_path="input.jsonl",
                    tasks=[
                        TaskSeed(prompt="one", params={"ready_after_seconds": 0.0}),
                        TaskSeed(prompt="two", params={"retry_until_attempt": 1}),
                    ],
                )

                scheduler = Scheduler(
                    storage=storage,
                    provider=MockImageProvider(),
                    settings=RuntimeSettings(
                        db_path=root / "image_factory.db",
                        output_dir=root / "outputs",
                        rate_limits=RateLimitSettings(
                            submit_rpm=600,
                            poll_rpm=600,
                            download_rpm=600,
                            submit_batch_size=10,
                            poll_batch_size=10,
                            download_batch_size=10,
                            idle_sleep_seconds=0.01,
                        ),
                        retry=RetrySettings(max_attempts=3, backoff_seconds=(0, 0, 0)),
                    ),
                )

                scheduler.run(provider_name="mock", max_cycles=50)

                counts = storage.aggregate_counts(batch.id)
                self.assertEqual(counts["succeeded"], 2)
                output_files = list((root / "outputs" / batch.id).glob("*.png"))
                self.assertEqual(len(output_files), 2)
            finally:
                storage.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_scheduler_uses_filename_param_for_output(self) -> None:
        root = Path("tests/.tmp") / f"scheduler-filename-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            storage = SqliteStorage(root / "image_factory.db")
            try:
                batch = storage.create_batch(
                    name="demo",
                    provider="mock",
                    source_path="input.jsonl",
                    tasks=[
                        TaskSeed(
                            prompt="one",
                            params={"filename": "hero_lin_chong_full", "ready_after_seconds": 0.0},
                        ),
                    ],
                )

                scheduler = Scheduler(
                    storage=storage,
                    provider=MockImageProvider(),
                    settings=RuntimeSettings(
                        db_path=root / "image_factory.db",
                        output_dir=root / "outputs",
                        rate_limits=RateLimitSettings(
                            submit_rpm=600,
                            poll_rpm=600,
                            download_rpm=600,
                            submit_batch_size=10,
                            poll_batch_size=10,
                            download_batch_size=10,
                            idle_sleep_seconds=0.01,
                        ),
                        retry=RetrySettings(max_attempts=3, backoff_seconds=(0, 0, 0)),
                    ),
                )

                scheduler.run(provider_name="mock", max_cycles=50)

                output_files = list((root / "outputs" / batch.id).glob("*.png"))
                self.assertEqual([path.name for path in output_files], ["hero_lin_chong_full.png"])
            finally:
                storage.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
