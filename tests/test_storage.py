import shutil
import uuid
from pathlib import Path
import unittest

from image_factory.models import TaskSeed
from image_factory.storage import SqliteStorage


class StorageTests(unittest.TestCase):
    def test_create_batch_persists_tasks(self) -> None:
        temp_dir = Path("tests/.tmp") / f"storage-{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            db_path = temp_dir / "image_factory.db"
            storage = SqliteStorage(db_path)
            try:
                batch = storage.create_batch(
                    name="demo",
                    provider="mock",
                    source_path="input.jsonl",
                    tasks=[TaskSeed(prompt="one"), TaskSeed(prompt="two")],
                )
                self.assertEqual(batch.total_tasks, 2)
                self.assertEqual(len(storage.list_tasks(batch.id, limit=10)), 2)
                counts = storage.aggregate_counts(batch.id)
                self.assertEqual(counts["pending"], 2)
            finally:
                storage.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
