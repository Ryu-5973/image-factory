from image_factory.providers.base import ImageProvider
from image_factory.providers.mock import MockImageProvider


def build_provider(name: str) -> ImageProvider:
    if name == "mock":
        return MockImageProvider()
    raise ValueError(f"Unknown provider: {name}")
