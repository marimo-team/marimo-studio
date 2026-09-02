"""Discover provider-qualified starting points for new views."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import Context, copy_context
from typing import Protocol

from marimo_studio._views.records import Starter
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    ProviderAvailability,
    ProviderStarter,
    ViewProvider,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.identity import starter_id

_AVAILABILITY_WORKERS = 8


class _CatalogProvider(ViewProvider, Protocol):
    key: str


def _provider_availability(
    providers: tuple[_CatalogProvider, ...],
) -> dict[str, ProviderAvailability]:
    if not providers:
        return {}
    with ThreadPoolExecutor(
        max_workers=min(_AVAILABILITY_WORKERS, len(providers)),
        thread_name_prefix="marimo-studio-provider-availability",
    ) as executor:
        futures: list[tuple[str, Future[ProviderAvailability]]] = []
        for provider in providers:
            context = copy_context()

            def availability(
                selected: _CatalogProvider = provider,
                selected_context: Context = context,
            ) -> ProviderAvailability:
                return selected_context.run(selected.availability)

            futures.append(
                (
                    provider.key,
                    executor.submit(availability),
                )
            )
        return {key: future.result() for key, future in futures}


def _starter_records() -> tuple[tuple[Starter, _CatalogProvider, ProviderStarter], ...]:
    registry = provider_registry()
    records = registry.starter_records()
    providers = {provider.key: provider for provider, _starter in records}
    availability = _provider_availability(tuple(providers.values()))
    return tuple(
        (
            _starter_record(provider, starter, availability[provider.key]),
            provider,
            starter,
        )
        for provider, starter in records
    )


def _starter_record(
    provider: _CatalogProvider,
    starter: ProviderStarter,
    availability: ProviderAvailability,
) -> Starter:
    return Starter(
        id=starter_id(provider.key, starter.key),
        title=starter.title,
        summary=starter.summary,
        provider=provider.key,
        documents=starter.documents,
        availability=availability,
    )


def starters() -> tuple[Starter, ...]:
    """Return every installed view starter."""
    return tuple(
        sorted(
            (starter for starter, _provider, _provider_starter in _starter_records()),
            key=lambda item: item.id,
        )
    )


def get_starter(identity: str) -> Starter:
    """Return one installed view starter."""
    available_starters = starters()
    matches = [item for item in available_starters if item.id == identity]
    if len(matches) != 1:
        available = ", ".join(item.id for item in available_starters) or "none"
        raise ConfigurationError(
            f"Unknown view starter {identity!r}. Installed starters: {available}"
        )
    return matches[0]


def resolve_starter(
    identity: str,
) -> tuple[Starter, ViewProvider, ProviderStarter]:
    """Return the public record and provider-local starter for one key."""
    provider_key, separator, local_key = identity.rpartition(":")
    if not separator or not provider_key or not local_key:
        raise ConfigurationError(
            f"Unknown view starter {identity!r}. Use '<provider>:<starter>'."
        )
    provider = provider_registry().get(provider_key)
    provider_starters = provider.starters()
    matches = [starter for starter in provider_starters if starter.key == local_key]
    if len(matches) != 1:
        available = (
            ", ".join(
                starter_id(provider.key, starter.key) for starter in provider_starters
            )
            or "none"
        )
        raise ConfigurationError(
            f"Unknown view starter {identity!r}. Installed starters: {available}"
        )
    provider_starter = matches[0]
    record = _starter_record(
        provider,
        provider_starter,
        provider.availability(),
    )
    return record, provider, provider_starter
