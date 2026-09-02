"""Expose one validated catalog of installed view providers.

Provider keys come from the installed distribution and entry-point name, so a
project does not depend on a provider's Python module path. Conflicting or
invalid registrations remain visible through diagnostics while healthy
providers and starters stay available.

Source access, builds, export, server routes, and provider diagnostics share one
process-wide registry so they agree about provider identity and starter
selection.
"""

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
