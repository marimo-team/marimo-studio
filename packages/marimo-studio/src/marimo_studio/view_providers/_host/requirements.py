"""Resolve installed provider distributions into an exact launch environment."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import version

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import NormalizedName, canonicalize_name

from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host import provider_registry

_STUDIO_DISTRIBUTION = canonicalize_name("marimo-studio")


def _exact_requirement(
    name: NormalizedName,
    package_version: str,
    extras: set[str],
) -> str:
    extra = f"[{','.join(sorted(extras))}]" if extras else ""
    value = f"{name}{extra}=={package_version}"
    try:
        return str(Requirement(value))
    except InvalidRequirement as error:
        raise ConfigurationError(
            f"Installed provider has an invalid distribution version: {value!r}"
        ) from error


def resolve_launch_requirements(
    provider_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return exact installed requirements for Studio and configured providers."""
    installed: dict[NormalizedName, tuple[str, set[str]]] = {
        _STUDIO_DISTRIBUTION: (version("marimo-studio"), set())
    }
    registry = provider_registry()
    for provider_id in sorted(set(provider_ids)):
        provider = registry.get(provider_id)
        try:
            requirement = Requirement(provider.requirement)
        except InvalidRequirement as error:
            raise ConfigurationError(
                f"View provider {provider_id!r} has an invalid Python requirement: "
                f"{provider.requirement!r}"
            ) from error
        name = canonicalize_name(requirement.name)
        distribution = canonicalize_name(provider.distribution)
        if name != distribution:
            raise ConfigurationError(
                f"View provider {provider_id!r} requirement names {name!r}, "
                f"expected {distribution!r}"
            )
        current = installed.get(distribution)
        provider_version = (
            current[0]
            if distribution == _STUDIO_DISTRIBUTION and current is not None
            else provider.version
        )
        if current is not None and current[0] != provider_version:
            raise ConfigurationError(
                f"Configured providers require conflicting installed versions of "
                f"{distribution!r}"
            )
        extras = set(requirement.extras)
        if current is not None:
            extras.update(current[1])
        installed[distribution] = (provider_version, extras)

    ordered = sorted(
        installed,
        key=lambda name: (name != _STUDIO_DISTRIBUTION, name),
    )
    return tuple(
        _exact_requirement(name, installed[name][0], installed[name][1])
        for name in ordered
    )
