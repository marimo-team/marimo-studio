"""Discover provider-qualified starting points for new views."""

from __future__ import annotations

import hashlib
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import Context, copy_context
from pathlib import Path
from typing import Protocol

from marimo_studio._views.records import Starter, StarterPreview
from marimo_studio._workspace.tools import notebook_tools
from marimo_studio.errors import StarterNotFoundError
from marimo_studio.view_providers import (
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    StarterSetting,
    ViewProvider,
)
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.identity import starter_id
from marimo_studio.view_providers._host.starters import starter_preview_media_type

_AVAILABILITY_WORKERS = 8


class _CatalogProvider(ViewProvider, Protocol):
    key: str
    info: ProviderInfo


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
        preview=(
            hashlib.sha256(starter.preview).hexdigest()
            if starter.preview is not None
            else None
        ),
        format=starter.format,
        icon=starter.icon,
        homepage=starter.homepage,
        requirement=provider.info.requirement,
        settings=starter.settings,
    )


def starters(notebook: Path | None = None) -> tuple[Starter, ...]:
    """Return every installed view starter, available for ``notebook``.

    Starters that can create a view in this environment come first.
    """
    with notebook_tools(notebook):
        records = _starter_records()
    return tuple(
        sorted(
            (starter for starter, _provider, _provider_starter in records),
            key=lambda item: (not item.availability.available, item.id),
        )
    )


def get_starter(identity: str) -> Starter:
    """Return one installed view starter."""
    available_starters = starters()
    matches = [item for item in available_starters if item.id == identity]
    if len(matches) != 1:
        raise _unknown_starter(identity)
    return matches[0]


def _unknown_starter(identity: str) -> StarterNotFoundError:
    return StarterNotFoundError(
        identity,
        available=tuple(
            sorted(
                starter_id(provider.key, starter.key)
                for provider, starter in provider_registry().starter_records()
            )
        ),
    )


def _provider_starter(identity: str) -> tuple[_CatalogProvider, ProviderStarter]:
    provider_key, separator, local_key = identity.rpartition(":")
    if not separator or not provider_key or not local_key:
        raise _unknown_starter(identity)
    provider = provider_registry().get(provider_key)
    matches = [starter for starter in provider.starters() if starter.key == local_key]
    if len(matches) != 1:
        raise _unknown_starter(identity)
    return provider, matches[0]


def starter_settings(identity: str) -> tuple[StarterSetting, ...]:
    """Return the settings one installed starter declares."""
    return _provider_starter(identity)[1].settings


def starter_preview(identity: str) -> StarterPreview | None:
    """Return one installed starter's preview image, or ``None`` without one."""
    _provider, starter = _provider_starter(identity)
    if starter.preview is None:
        return None
    media_type = starter_preview_media_type(starter.preview)
    assert media_type is not None
    return StarterPreview(
        content=starter.preview,
        media_type=media_type,
        digest=hashlib.sha256(starter.preview).hexdigest(),
    )


def resolve_starter(
    identity: str,
    notebook: Path | None = None,
) -> tuple[Starter, ViewProvider, ProviderStarter]:
    """Return the public record and provider-local starter for one key.

    The record reports the provider's availability for ``notebook``.
    """
    provider, provider_starter = _provider_starter(identity)
    with notebook_tools(notebook):
        availability = provider.availability()
    record = _starter_record(provider, provider_starter, availability)
    return record, provider, provider_starter
