"""Platform adapters (SPEC 5.1)."""

from app.platform.base import PlatformAdapter, PlatformInfo
from app.platform.factory import detect_platform_name, get_platform_adapter, make_platform_adapter

__all__ = [
    "PlatformAdapter",
    "PlatformInfo",
    "detect_platform_name",
    "get_platform_adapter",
    "make_platform_adapter",
]
