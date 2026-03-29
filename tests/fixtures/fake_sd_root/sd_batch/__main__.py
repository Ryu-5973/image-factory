from __future__ import annotations

import argparse
import base64
import csv
import json
from pathlib import Path

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+tH9QAAAAASUVORK5CYII="
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config")
    parser.add_argument("--skip-existing")
    parser.add_argument("--model")
    parser.add_argument("--batch-size")
    parser.add_argument("--max-retries")
    parser.add_argument("--device")
    parser.add_argument("--dtype")
    parser.add_argument("--variant")
    parser.add_argument("--default-negative-prompt")
    parser.add_argument("--default-width")
    parser.add_argument("--default-height")
    parser.add_argument("--default-steps")
    parser.add_argument("--default-guidance-scale")
    parser.add_argument("--default-num-images")
    parser.add_argument("--prompt-template")
    parser.add_argument("--attention-slicing")
    parser.add_argument("--vae-tiling")
    parser.add_argument("--cpu-offload", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--enable-xformers", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "manifest.jsonl"
    failures_path = output_dir / "failures.jsonl"

    with Path(args.input).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            job = {
                "job_id": row["job_id"],
                "prompt": row["prompt"],
                "negative_prompt": row.get("negative_prompt", ""),
            }
            if "FAIL" in row["prompt"]:
                _append_jsonl(
                    failures_path,
                    {"status": "failed", "job": job, "error": "simulated failure"},
                )
                continue

            image_path = images_dir / f"{row['filename']}.png"
            image_path.write_bytes(_TINY_PNG)
            _append_jsonl(
                manifest_path,
                {
                    "status": "completed",
                    "job": job,
                    "image_path": str(image_path),
                    "seed": row.get("seed") or "0",
                },
            )
    return 0


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
