"""Discover installed view providers and enforce host policy."""

from threading import Lock

from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_REQUIREMENTS,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

_REGISTRY: ProviderRegistry | None = None
_REGISTRY_LOCK = Lock()


def provider_registry() -> ProviderRegistry:
    """Return the process-wide provider registry."""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = ProviderRegistry.discover(BUNDLED_PROVIDER_REQUIREMENTS)
    return _REGISTRY
