from __future__ import annotations

import csv
import json
from pathlib import Path

from image_factory.models import TaskSeed


def load_task_seeds(input_path: Path) -> list[TaskSeed]:
    suffix = input_path.suffix.lower()
    if suffix == ".jsonl":
        return _load_jsonl(input_path)
    if suffix == ".csv":
        return _load_csv(input_path)
    if suffix in {".txt", ".prompts"}:
        return _load_text(input_path)
    raise ValueError(f"Unsupported input format: {input_path.suffix}")


def _load_jsonl(input_path: Path) -> list[TaskSeed]:
    tasks: list[TaskSeed] = []
    with input_path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            if isinstance(payload, str):
                tasks.append(TaskSeed(prompt=payload))
                continue
            if "prompt" not in payload:
                raise ValueError(f"JSONL line {index} is missing 'prompt'")
            params = dict(payload)
            prompt = str(params.pop("prompt"))
            tasks.append(TaskSeed(prompt=prompt, params=params))
    return tasks


def _load_csv(input_path: Path) -> list[TaskSeed]:
    tasks: list[TaskSeed] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "prompt" not in reader.fieldnames:
            raise ValueError("CSV input must contain a 'prompt' column")
        for row in reader:
            prompt = row.pop("prompt", "")
            params = {key: value for key, value in row.items() if value not in {None, ""}}
            tasks.append(TaskSeed(prompt=prompt, params=params))
    return tasks


def _load_text(input_path: Path) -> list[TaskSeed]:
    tasks: list[TaskSeed] = []
    with input_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            prompt = line.strip()
            if prompt:
                tasks.append(TaskSeed(prompt=prompt))
    return tasks
