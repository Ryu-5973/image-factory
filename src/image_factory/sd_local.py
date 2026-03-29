from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from image_factory.config import RetrySettings
from image_factory.models import TaskRecord, TaskStatus, utc_now, utc_now_iso
from image_factory.storage import SqliteStorage


@dataclass(slots=True)
class StableDiffusionRunOptions:
    batch_id: str
    stable_diffusion_root: Path
    image_factory_output_dir: Path
    provider: str = "sd-local"
    python_executable: Path | None = None
    sd_config_path: Path | None = None
    max_tasks_per_run: int = 100
    retry: RetrySettings = field(default_factory=RetrySettings)
    model: str | None = None
    batch_size: int | None = None
    max_retries: int | None = None
    device: str | None = None
    dtype: str | None = None
    variant: str | None = None
    default_negative_prompt: str | None = None
    default_width: int | None = None
    default_height: int | None = None
    default_steps: int | None = None
    default_guidance_scale: float | None = None
    default_num_images: int | None = None
    prompt_template: str | None = None
    attention_slicing: bool | None = None
    vae_tiling: bool | None = None
    skip_existing: bool | None = False
    cpu_offload: bool = False
    local_files_only: bool = False
    enable_xformers: bool = False


@dataclass(slots=True)
class StableDiffusionRunSummary:
    batch_id: str
    run_id: str
    claimed: int
    succeeded: int
    failed: int
    retried: int
    output_dir: str
    command: list[str]
    return_code: int


class StableDiffusionBatchExecutor:
    def __init__(self, storage: SqliteStorage, options: StableDiffusionRunOptions):
        self.storage = storage
        self.options = options

    def run_once(self) -> StableDiffusionRunSummary:
        batch = self.storage.get_batch(self.options.batch_id)
        if batch.provider != self.options.provider:
            raise ValueError(
                f"Batch {batch.id} provider is {batch.provider!r}, expected {self.options.provider!r}"
            )

        self.storage.reset_submitting_tasks(provider=self.options.provider, batch_id=self.options.batch_id)
        self.storage.promote_ready_tasks()
        tasks = self.storage.claim_ready_tasks(
            self.options.max_tasks_per_run,
            provider=self.options.provider,
            batch_id=self.options.batch_id,
        )
        if not tasks:
            return StableDiffusionRunSummary(
                batch_id=batch.id,
                run_id="none",
                claimed=0,
                succeeded=0,
                failed=0,
                retried=0,
                output_dir="",
                command=[],
                return_code=0,
            )

        run_id = f"sd_run_{utc_now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        run_dir = (self.options.image_factory_output_dir / batch.id / "stable_diffusion" / run_id).resolve()
        input_path = run_dir / "input.csv"
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_input_csv(input_path, tasks)

        command = self._build_command(input_path=input_path, output_path=run_dir)
        try:
            completed = subprocess.run(
                command,
                cwd=self.options.stable_diffusion_root,
                env=self._build_env(),
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            imported = self._import_results(tasks=tasks, run_dir=run_dir, process_error=str(exc))
            return StableDiffusionRunSummary(
                batch_id=batch.id,
                run_id=run_id,
                claimed=len(tasks),
                succeeded=imported["succeeded"],
                failed=imported["failed"],
                retried=imported["retried"],
                output_dir=str(run_dir),
                command=command,
                return_code=1,
            )

        imported = self._import_results(tasks=tasks, run_dir=run_dir, process_error=self._process_error(completed))
        return StableDiffusionRunSummary(
            batch_id=batch.id,
            run_id=run_id,
            claimed=len(tasks),
            succeeded=imported["succeeded"],
            failed=imported["failed"],
            retried=imported["retried"],
            output_dir=str(run_dir),
            command=command,
            return_code=completed.returncode,
        )

    def _build_command(self, *, input_path: Path, output_path: Path) -> list[str]:
        python_executable = self.options.python_executable or (
            self.options.stable_diffusion_root / ".venv" / "Scripts" / "python.exe"
        )
        command = [_command_executable(python_executable), "-m", "sd_batch"]
        if self.options.sd_config_path:
            command.extend(["--config", str(Path(self.options.sd_config_path).resolve())])
        command.extend(["--input", str(input_path.resolve()), "--output", str(output_path.resolve())])
        command.extend(["--skip-existing", _bool_arg(self.options.skip_existing)])

        scalar_args: list[tuple[str, Any]] = [
            ("--model", self.options.model),
            ("--batch-size", self.options.batch_size),
            ("--max-retries", self.options.max_retries),
            ("--device", self.options.device),
            ("--dtype", self.options.dtype),
            ("--variant", self.options.variant),
            ("--default-negative-prompt", self.options.default_negative_prompt),
            ("--default-width", self.options.default_width),
            ("--default-height", self.options.default_height),
            ("--default-steps", self.options.default_steps),
            ("--default-guidance-scale", self.options.default_guidance_scale),
            ("--default-num-images", self.options.default_num_images),
            ("--prompt-template", self.options.prompt_template),
            ("--attention-slicing", _optional_bool_arg(self.options.attention_slicing)),
            ("--vae-tiling", _optional_bool_arg(self.options.vae_tiling)),
        ]
        for flag, value in scalar_args:
            if value is None:
                continue
            command.extend([flag, str(value)])

        if self.options.cpu_offload:
            command.append("--cpu-offload")
        if self.options.local_files_only:
            command.append("--local-files-only")
        if self.options.enable_xformers:
            command.append("--enable-xformers")
        return command

    def _build_env(self) -> dict[str, str]:
        root = self.options.stable_diffusion_root
        temp_dir = root / ".tmp"
        hf_cache = root / "hf_cache"
        temp_dir.mkdir(parents=True, exist_ok=True)
        hf_cache.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        env["HF_HOME"] = str(hf_cache)
        return env

    def _write_input_csv(self, input_path: Path, tasks: list[TaskRecord]) -> None:
        fieldnames = [
            "job_id",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "steps",
            "guidance_scale",
            "num_images",
            "seed",
            "filename",
        ]
        with input_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for task in tasks:
                params = task.params
                writer.writerow(
                    {
                        "job_id": _job_id_for_task(task.id),
                        "prompt": task.prompt,
                        "negative_prompt": params.get("negative_prompt", ""),
                        "width": params.get("width", ""),
                        "height": params.get("height", ""),
                        "steps": params.get("steps", ""),
                        "guidance_scale": params.get("guidance_scale", ""),
                        "num_images": params.get("num_images", ""),
                        "seed": params.get("seed", ""),
                        "filename": params.get("filename", f"task-{task.id:06d}"),
                    }
                )

    def _import_results(self, *, tasks: list[TaskRecord], run_dir: Path, process_error: str | None) -> dict[str, int]:
        task_map = {task.id: task for task in tasks}
        seen: set[int] = set()
        succeeded = 0
        failed = 0
        retried = 0

        manifest_path = run_dir / "manifest.jsonl"
        if manifest_path.exists():
            for payload in _load_jsonl(manifest_path):
                task_id = _task_id_from_payload(payload)
                if task_id is None or task_id not in task_map or task_id in seen:
                    continue
                image_path = Path(str(payload.get("image_path", "")))
                if not image_path.exists():
                    continue
                seen.add(task_id)
                metadata = {
                    "executor": "sd-local",
                    "run_dir": str(run_dir),
                    "sd_manifest_entry": payload,
                }
                self.storage.mark_task_success(task_id, result_path=str(image_path), remote_metadata=metadata)
                succeeded += 1

        failures_path = run_dir / "failures.jsonl"
        if failures_path.exists():
            for payload in _load_jsonl(failures_path):
                task_id = _task_id_from_payload(payload)
                if task_id is None or task_id not in task_map or task_id in seen:
                    continue
                seen.add(task_id)
                self.storage.mark_task_failure(
                    task_id,
                    status=TaskStatus.FAILED,
                    error_code="sd_job_failed",
                    error_message=str(payload.get("error", "Stable Diffusion job failed")),
                )
                failed += 1

        unseen_ids = [task.id for task in tasks if task.id not in seen]
        for task_id in unseen_ids:
            task = task_map[task_id]
            message = process_error or "Stable Diffusion run finished without a manifest or failure record"
            if task.attempt >= self.options.retry.max_attempts:
                self.storage.mark_task_failure(
                    task_id,
                    status=TaskStatus.DEAD_LETTER,
                    error_code="sd_missing_result",
                    error_message=message,
                )
                failed += 1
                continue
            next_retry_at = (utc_now() + _retry_delta_seconds(self.options.retry, task.attempt)).isoformat()
            self.storage.mark_task_retry(
                task_id,
                error_code="sd_missing_result",
                error_message=message,
                next_retry_at=next_retry_at,
            )
            retried += 1

        return {"succeeded": succeeded, "failed": failed, "retried": retried}

    @staticmethod
    def _process_error(completed: subprocess.CompletedProcess[str]) -> str | None:
        if completed.returncode == 0:
            return None
        parts = [part.strip() for part in [completed.stderr, completed.stdout] if part and part.strip()]
        if not parts:
            return f"Stable Diffusion batch process exited with code {completed.returncode}"
        joined = "\n".join(parts)
        return f"Stable Diffusion batch process exited with code {completed.returncode}\n{joined}"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if raw:
                payloads.append(json.loads(raw))
    return payloads


def _job_id_for_task(task_id: int) -> str:
    return f"task_{task_id}"


def _task_id_from_payload(payload: dict[str, Any]) -> int | None:
    job = payload.get("job", {})
    job_id = payload.get("job_id") or job.get("job_id")
    if not isinstance(job_id, str) or not job_id.startswith("task_"):
        return None
    try:
        return int(job_id.split("_", 1)[1])
    except ValueError:
        return None


def _bool_arg(value: bool) -> str:
    return "true" if value else "false"


def _optional_bool_arg(value: bool | None) -> str | None:
    if value is None:
        return None
    return _bool_arg(value)


def _retry_delta_seconds(retry: RetrySettings, attempt: int):
    from datetime import timedelta

    return timedelta(seconds=retry.delay_for_attempt(attempt))


def default_python_executable(stable_diffusion_root: Path) -> Path:
    default_path = stable_diffusion_root / ".venv" / "Scripts" / "python.exe"
    if default_path.exists():
        return default_path
    return Path(sys.executable)


def _command_executable(value: Path | str) -> str:
    text = str(value)
    if any(sep in text for sep in ("\\", "/")) or Path(text).suffix:
        return str(Path(text).resolve())
    return text
