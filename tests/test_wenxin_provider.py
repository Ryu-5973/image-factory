import io
from unittest.mock import patch
import unittest

from PIL import Image

from image_factory.models import TaskRecord, TaskStatus
from image_factory.providers.wenxin import WenxinImageProvider, WenxinSettings


class WenxinProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = WenxinImageProvider(
            WenxinSettings(
                api_key="test-api-key",
                endpoint="https://qianfan.baidubce.com/v2/images/generations",
                model="qwen-image",
            )
        )

    def test_submit_uses_v2_payload(self) -> None:
        task = _build_task(
            prompt="hero portrait",
            params={"width": 512, "height": 512, "negative_prompt": "bad hands"},
        )
        response = {"id": "img_1", "data": [{"url": "https://example.com/image.png"}]}
        with patch.object(self.provider, "_request_json", return_value=response) as request:
            result = self.provider.submit(task)

        self.assertEqual(result.remote_task_id, "img_1")
        payload = request.call_args.args[2]
        self.assertEqual(payload["model"], "qwen-image")
        self.assertEqual(payload["prompt"], "hero portrait")
        self.assertEqual(payload["negative_prompt"], "bad hands")
        self.assertEqual(payload["size"], "512x512")

    def test_poll_succeeds_with_submit_image_data(self) -> None:
        task = _build_task(
            prompt="hero portrait",
            remote_task_id="img_1",
            remote_metadata={"image_data": [{"url": "https://example.com/image.png"}]},
        )
        result = self.provider.poll(task)
        self.assertEqual(result.state.value, "succeeded")
        self.assertEqual(result.remote_metadata["image_data"][0]["url"], "https://example.com/image.png")

    def test_fetch_result_downloads_first_image(self) -> None:
        task = _build_task(
            prompt="hero portrait",
            remote_metadata={"image_data": [{"url": "https://example.com/image.png"}]},
        )

        image = Image.new("RGB", (2, 2), color=(255, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        jpeg_bytes = buffer.getvalue()

        class _Response:
            headers = {"Content-Type": "image/jpeg"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return jpeg_bytes

        with patch("image_factory.providers.wenxin.urlopen", return_value=_Response()):
            result = self.provider.fetch_result(task)

        self.assertEqual(result.file_extension, "png")
        self.assertTrue(result.content.startswith(b"\x89PNG\r\n\x1a\n"))


def _build_task(
    *,
    prompt: str,
    params: dict | None = None,
    remote_task_id: str | None = None,
    remote_metadata: dict | None = None,
) -> TaskRecord:
    return TaskRecord(
        id=1,
        batch_id="batch_1",
        input_index=0,
        prompt=prompt,
        params=params or {},
        provider="wenxin",
        status=TaskStatus.READY,
        attempt=1,
        remote_task_id=remote_task_id,
        remote_metadata=remote_metadata or {},
        result_path=None,
        error_code=None,
        error_message=None,
        next_poll_at=None,
        next_retry_at=None,
        created_at="2026-03-29T00:00:00+00:00",
        updated_at="2026-03-29T00:00:00+00:00",
        completed_at=None,
    )
