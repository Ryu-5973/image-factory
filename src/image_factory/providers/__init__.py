from image_factory.providers.base import ImageProvider
from image_factory.providers.mock import MockImageProvider
from image_factory.providers.wenxin import WenxinImageProvider


def build_provider(name: str) -> ImageProvider:
    if name == "mock":
        return MockImageProvider()
    if name == "wenxin":
        return WenxinImageProvider()
    raise ValueError(f"Unknown provider: {name}")
