from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RateLimitSettings:
    submit_rpm: int = 60
    poll_rpm: int = 240
    download_rpm: int = 120
    submit_batch_size: int = 10
    poll_batch_size: int = 20
    download_batch_size: int = 20
    idle_sleep_seconds: float = 1.0


@dataclass(slots=True)
class RetrySettings:
    max_attempts: int = 4
    backoff_seconds: tuple[int, ...] = (15, 30, 60, 180)

    def delay_for_attempt(self, attempt: int) -> int:
        if attempt <= 0:
            return self.backoff_seconds[0]
        index = min(attempt - 1, len(self.backoff_seconds) - 1)
        return self.backoff_seconds[index]


@dataclass(slots=True)
class RuntimeSettings:
    db_path: Path = Path("data/image_factory.db")
    output_dir: Path = Path("outputs")
    rate_limits: RateLimitSettings = field(default_factory=RateLimitSettings)
    retry: RetrySettings = field(default_factory=RetrySettings)
