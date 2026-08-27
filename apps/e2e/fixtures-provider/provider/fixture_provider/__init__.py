"""External providers used by Studio browser acceptance."""

from fixture_provider.report import provider
from fixture_provider.web import multi_provider

__all__ = ["multi_provider", "provider"]
