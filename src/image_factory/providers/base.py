from __future__ import annotations

from abc import ABC, abstractmethod

from image_factory.models import FetchResult, PollResult, SubmissionResult, TaskRecord


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ProviderRetryableError(ProviderError):
    """A temporary provider error."""


class ProviderFatalError(ProviderError):
    """A permanent provider error."""


class ImageProvider(ABC):
    name: str

    @abstractmethod
    def submit(self, task: TaskRecord) -> SubmissionResult:
        raise NotImplementedError

    @abstractmethod
    def poll(self, task: TaskRecord) -> PollResult:
        raise NotImplementedError

    @abstractmethod
    def fetch_result(self, task: TaskRecord) -> FetchResult:
        raise NotImplementedError
