from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class TokenBucket:
    rate: int
    per_seconds: float
    burst: int | None = None
    capacity: float = field(init=False)
    tokens: float = field(init=False)
    refill_rate: float = field(init=False)
    updated_at: float = field(init=False)

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be greater than zero")
        if self.per_seconds <= 0:
            raise ValueError("per_seconds must be greater than zero")
        self.capacity = float(self.burst or self.rate)
        self.tokens = self.capacity
        self.refill_rate = self.rate / self.per_seconds
        self.updated_at = time.monotonic()

    def _refill(self) -> None:
        current = time.monotonic()
        elapsed = current - self.updated_at
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.updated_at = current

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def wait_time(self, cost: float = 1.0) -> float:
        self._refill()
        if self.tokens >= cost:
            return 0.0
        missing = cost - self.tokens
        return missing / self.refill_rate
