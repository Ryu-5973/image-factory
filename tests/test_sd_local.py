import shutil
import sys
import uuid
from pathlib import Path
import unittest

from image_factory.config import RetrySettings
from image_factory.models import TaskSeed
from image_factory.sd_local import StableDiffusionBatchExecutor, StableDiffusionRunOptions
from image_factory.storage import SqliteStorage


class StableDiffusionExecutorTests(unittest.TestCase):
    def test_run_once_imports_manifest_and_failures(self) -> None:
        root = Path("tests/.tmp") / f"sd-local-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            storage = SqliteStorage(root / "image_factory.db")
            try:
                batch = storage.create_batch(
                    name="sd-local-demo",
                    provider="sd-local",
                    source_path="input.jsonl",
                    tasks=[
                        TaskSeed(prompt="good image", params={"width": 512, "height": 512}),
                        TaskSeed(prompt="FAIL image", params={"width": 512, "height": 512}),
                    ],
                )
                options = StableDiffusionRunOptions(
                    batch_id=batch.id,
                    stable_diffusion_root=Path("tests/fixtures/fake_sd_root"),
                    image_factory_output_dir=root / "outputs",
                    python_executable=Path(sys.executable),
                    retry=RetrySettings(max_attempts=2, backoff_seconds=(0, 0)),
                )

                summary = StableDiffusionBatchExecutor(storage, options).run_once()

                self.assertEqual(summary.claimed, 2)
                self.assertEqual(summary.succeeded, 1)
                self.assertEqual(summary.failed, 1)
                tasks = storage.list_tasks(batch.id, limit=10)
                statuses = {task.prompt: task.status.value for task in tasks}
                self.assertEqual(statuses["good image"], "succeeded")
                self.assertEqual(statuses["FAIL image"], "failed")
                success_task = next(task for task in tasks if task.prompt == "good image")
                self.assertTrue(Path(success_task.result_path or "").exists())
            finally:
                storage.close()
        finally:
            shutil.rmtree(root, ignore_errors=True)
