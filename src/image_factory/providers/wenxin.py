from __future__ import annotations

import base64
import io
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from image_factory.models import FetchResult, PollResult, RemoteTaskState, SubmissionResult, TaskRecord
from image_factory.providers.base import ImageProvider, ProviderFatalError, ProviderRetryableError


@dataclass(slots=True)
class WenxinSettings:
    api_key: str
    endpoint: str = "https://qianfan.baidubce.com/v2/images/generations"
    model: str = "qwen-image"
    poll_after_seconds: float = 0.0
    n: int = 1


class WenxinImageProvider(ImageProvider):
    name = "wenxin"

    def __init__(self, settings: WenxinSettings | None = None):
        self.settings = settings or WenxinSettings(
            api_key=_require_env("QIANFAN_API_KEY"),
            endpoint=os.environ.get("QIANFAN_IMAGE_ENDPOINT", "https://qianfan.baidubce.com/v2/images/generations"),
            model=os.environ.get("QIANFAN_IMAGE_MODEL", "qwen-image"),
            poll_after_seconds=float(os.environ.get("QIANFAN_IMAGE_POLL_AFTER_SECONDS", "0")),
            n=int(os.environ.get("QIANFAN_IMAGE_N", "1")),
        )

    def submit(self, task: TaskRecord) -> SubmissionResult:
        payload = self._build_payload(task)
        response = self._request_json("POST", self.settings.endpoint, payload)

        image_data = _extract_image_data(response)
        if not image_data:
            raise ProviderFatalError("wenxin_bad_response", "Wenxin v2 response did not contain image data")

        remote_metadata = {
            "submit_response": response,
            "image_data": image_data,
            "wenxin_model": payload["model"],
        }
        return SubmissionResult(
            remote_task_id=str(response.get("id") or uuid.uuid4().hex),
            remote_metadata=remote_metadata,
            poll_after_seconds=self.settings.poll_after_seconds,
        )

    def poll(self, task: TaskRecord) -> PollResult:
        image_data = task.remote_metadata.get("image_data") or _extract_image_data(task.remote_metadata.get("submit_response", {}))
        if image_data:
            remote_metadata = dict(task.remote_metadata)
            remote_metadata["image_data"] = image_data
            return PollResult(state=RemoteTaskState.SUCCEEDED, remote_metadata=remote_metadata)
        return PollResult(
            state=RemoteTaskState.FAILED,
            remote_metadata=task.remote_metadata,
            error_code="wenxin_missing_image_data",
            error_message="Wenxin v2 response did not include image data",
        )

    def fetch_result(self, task: TaskRecord) -> FetchResult:
        image_data = task.remote_metadata.get("image_data") or _extract_image_data(task.remote_metadata.get("submit_response", {}))
        if not image_data:
            raise ProviderFatalError("wenxin_missing_image_data", "No image data found in Wenxin task result")

        first = image_data[0]
        if "b64_json" in first:
            try:
                content = base64.b64decode(first["b64_json"])
            except Exception as exc:
                raise ProviderFatalError("wenxin_invalid_b64", f"Invalid b64_json in Wenxin response: {exc}") from exc
            return FetchResult(
                content=content,
                file_extension="png",
                metadata={"image_data": image_data, "selected_image": first},
            )

        image_url = first.get("url")
        if not image_url:
            raise ProviderFatalError("wenxin_missing_image_url", "No image URL found in Wenxin response")

        try:
            with urlopen(image_url, timeout=120) as response:
                content = response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ProviderRetryableError("wenxin_download_error", f"Failed to download Wenxin image: {exc}") from exc

        png_content = _convert_to_png(content)
        return FetchResult(
            content=png_content,
            file_extension="png",
            metadata={"image_data": image_data, "selected_image": first},
        )

    def _build_payload(self, task: TaskRecord) -> dict[str, Any]:
        params = dict(task.params)
        payload: dict[str, Any] = {
            "model": str(params.get("wenxin_model", self.settings.model)),
            "prompt": task.prompt,
        }

        if params.get("negative_prompt"):
            payload["negative_prompt"] = str(params["negative_prompt"])

        size = params.get("size") or _size_from_dimensions(params.get("width"), params.get("height"))
        if size:
            payload["size"] = size

        if params.get("response_format"):
            payload["response_format"] = str(params["response_format"])

        n_value = params.get("n", self.settings.n)
        if n_value is not None:
            payload["n"] = int(n_value)

        user_value = params.get("user")
        if user_value:
            payload["user"] = str(user_value)

        image_value = params.get("image") or params.get("reference_image")
        if image_value:
            payload["image"] = image_value

        return payload

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url=url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self._raise_provider_error(exc.code, body)
        except (URLError, TimeoutError) as exc:
            raise ProviderRetryableError("wenxin_network_error", str(exc)) from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderRetryableError("wenxin_invalid_json", f"Invalid JSON response: {exc}") from exc

        if parsed.get("error"):
            self._raise_provider_error(None, raw)
        return parsed

    @staticmethod
    def _raise_provider_error(http_status: int | None, body: str) -> None:
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None

        error_root = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
        error_code = _extract_error_code(error_root, default=f"http_{http_status or 'error'}")
        message = _extract_error_message(error_root, default=body.strip() or "Wenxin API request failed")

        retryable_statuses = {408, 429, 500, 502, 503, 504}
        retryable_codes = {
            "rate_limit_exceeded",
            "rpm_rate_limit_exceeded",
            "qps_rate_limit_exceeded",
            "internal_error",
            "server_error",
            "timeout",
        }
        if http_status in retryable_statuses or error_code in retryable_codes:
            raise ProviderRetryableError(error_code, message)
        raise ProviderFatalError(error_code, message)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    raise ValueError(f"Missing required environment variable: {name}")


def _extract_error_code(payload: dict[str, Any], default: str) -> str:
    for key in ("code", "error_code", "type"):
        value = payload.get(key)
        if value not in {None, ""}:
            return str(value)
    return default


def _extract_error_message(payload: dict[str, Any], default: str) -> str:
    for key in ("message", "error_msg", "error", "msg"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return str(value)
    return default


def _extract_image_data(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            normalized = [item for item in data if isinstance(item, dict) and ("url" in item or "b64_json" in item)]
            if normalized:
                return normalized
        for value in payload.values():
            found = _extract_image_data(value)
            if found:
                return found
        return []
    if isinstance(payload, list):
        normalized = [item for item in payload if isinstance(item, dict) and ("url" in item or "b64_json" in item)]
        if normalized:
            return normalized
        for item in payload:
            found = _extract_image_data(item)
            if found:
                return found
    return []


def _size_from_dimensions(width: Any, height: Any) -> str | None:
    try:
        width_value = int(width)
        height_value = int(height)
    except (TypeError, ValueError):
        return None
    if width_value <= 0 or height_value <= 0:
        return None
    return f"{width_value}x{height_value}"


def _convert_to_png(content: bytes) -> bytes:
    try:
        image = Image.open(io.BytesIO(content))
    except Exception as exc:
        raise ProviderFatalError("wenxin_invalid_image", f"Failed to parse Wenxin image bytes: {exc}") from exc

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
