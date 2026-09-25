"""Resolve provider bootstrap requirements from durable Python metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

from packaging.markers import UndefinedEnvironmentName, default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import InvalidVersion, Version

from marimo_studio.errors import ConfigurationError

MarkerEnvironment: TypeAlias = Mapping[str, str]
_STUDIO_DISTRIBUTION = canonicalize_name("marimo-studio")
_MARKER_ENVIRONMENT_FIELDS = frozenset(default_environment())


@dataclass(frozen=True)
class DependencyConstraint:
    """Requirements and uv source ownership for one distribution."""

    distribution: NormalizedName
    requirements: tuple[Requirement, ...]
    source_owned: bool


def _dependency_values(metadata: Mapping[str, object]) -> object:
    project = metadata.get("project")
    if isinstance(project, Mapping):
        return project.get("dependencies", ())
    return metadata.get("dependencies", ())


def _has_source(metadata: Mapping[str, object], distribution: NormalizedName) -> bool:
    tool = metadata.get("tool")
    uv = tool.get("uv") if isinstance(tool, Mapping) else None
    sources = uv.get("sources") if isinstance(uv, Mapping) else None
    return isinstance(sources, Mapping) and any(
        canonicalize_name(str(name)) == distribution for name in sources
    )


def dependency_constraint(
    metadata: Mapping[str, object],
    distribution: str,
) -> DependencyConstraint:
    """Return requirements and uv source ownership for ``distribution``."""
    name = canonicalize_name(distribution)
    values = _dependency_values(metadata)
    if not isinstance(values, list | tuple) or not all(
        isinstance(value, str) for value in values
    ):
        raise ConfigurationError("Python dependencies must be an array of strings")
    requirements = []
    for value in values:
        try:
            requirement = Requirement(value)
        except InvalidRequirement:
            continue
        if canonicalize_name(requirement.name) == name:
            requirements.append(requirement)
    return DependencyConstraint(
        name,
        tuple(requirements),
        _has_source(metadata, name),
    )


def studio_dependency_constraint(
    metadata: Mapping[str, object],
) -> DependencyConstraint:
    """Return the Studio dependency constraint in Python metadata."""
    return dependency_constraint(metadata, _STUDIO_DISTRIBUTION)


def _active_requirements(
    constraints: Iterable[DependencyConstraint],
    marker_environment: MarkerEnvironment | None,
) -> tuple[Requirement, ...]:
    active = []
    for constraint in constraints:
        for requirement in constraint.requirements:
            marker = requirement.marker
            if marker is None:
                active.append(requirement)
                continue
            if marker_environment is None:
                raise ConfigurationError(
                    "Cannot evaluate dependency markers before the target Python "
                    "environment is known"
                )
            missing = _MARKER_ENVIRONMENT_FIELDS.difference(marker_environment)
            if missing:
                raise ConfigurationError(
                    "Dependency marker environment is incomplete: "
                    + ", ".join(sorted(missing))
                )
            try:
                selected = marker.evaluate(
                    environment=marker_environment,
                    context="requirement",
                )
            except UndefinedEnvironmentName as error:
                raise ConfigurationError(
                    f"Dependency marker uses an unknown environment name: {marker}"
                ) from error
            if selected:
                active.append(requirement)
    return tuple(active)


def uses_dependency_source(
    constraint: DependencyConstraint,
    *,
    marker_environment: MarkerEnvironment | None,
) -> bool:
    """Return whether a uv source belongs to an active dependency branch."""
    return constraint.source_owned and bool(
        _active_requirements((constraint,), marker_environment)
    )


def _exact_version(requirement: Requirement) -> Version | None:
    specifiers = tuple(requirement.specifier)
    if (
        len(specifiers) != 1
        or specifiers[0].operator != "=="
        or "*" in specifiers[0].version
    ):
        return None
    try:
        return Version(specifiers[0].version)
    except InvalidVersion as error:
        raise ConfigurationError(
            f"Dependency has an invalid exact version: {requirement}"
        ) from error


def _render_requirement(
    requirement: Requirement,
    extras: set[str],
    *,
    include_marker: bool = False,
) -> str:
    combined = sorted(requirement.extras | extras)
    extra_text = f"[{','.join(combined)}]" if combined else ""
    if requirement.url is not None:
        rendered = f"{requirement.name}{extra_text} @ {requirement.url}"
    else:
        rendered = f"{requirement.name}{extra_text}{requirement.specifier}"
    if include_marker and requirement.marker is not None:
        rendered = f"{rendered}; {requirement.marker}"
    return rendered


def effective_dependency_requirement(
    launch_requirement: str,
    constraints: Iterable[DependencyConstraint],
    *,
    marker_environment: MarkerEnvironment | None,
    require_declared: bool = False,
) -> str:
    """Resolve one marker-free requirement for a concrete target environment."""
    try:
        base = Requirement(launch_requirement)
    except InvalidRequirement as error:
        raise ConfigurationError(
            f"Invalid launch requirement: {launch_requirement!r}"
        ) from error
    distribution = canonicalize_name(base.name)
    selected_constraints = tuple(constraints)
    if any(item.distribution != distribution for item in selected_constraints):
        raise ConfigurationError(
            f"Dependency constraints do not describe {distribution!r}"
        )
    active = _active_requirements(selected_constraints, marker_environment)
    if require_declared and not active:
        raise ConfigurationError(
            f"Configured provider requires {distribution!r}, but the target "
            "metadata has no active dependency for it"
        )
    direct = tuple(item for item in active if item.url is not None)
    direct_urls = {item.url for item in direct}
    if len(direct_urls) > 1:
        raise ConfigurationError(
            f"Target metadata declares conflicting direct sources for {distribution!r}"
        )
    versioned = tuple(item for item in active if str(item.specifier))
    active_sources = tuple(
        constraint
        for constraint in selected_constraints
        if uses_dependency_source(
            constraint,
            marker_environment=marker_environment,
        )
    )
    if direct and active_sources:
        raise ConfigurationError(
            f"Target metadata combines a direct source and uv source for "
            f"{distribution!r}"
        )
    if len(active_sources) > 1:
        raise ConfigurationError(
            f"Target metadata declares multiple uv sources for {distribution!r}"
        )
    if direct and versioned:
        raise ConfigurationError(
            f"Target metadata combines a direct source and version range for "
            f"{distribution!r}"
        )
    exact = tuple(
        (version, item)
        for item in versioned
        if (version := _exact_version(item)) is not None
    )
    exact_versions = {version for version, _item in exact}
    if len(exact_versions) > 1:
        rendered = ", ".join(str(version) for version in sorted(exact_versions))
        raise ConfigurationError(
            f"Target metadata requires conflicting exact {distribution!r} "
            f"versions: {rendered}"
        )
    source = next(
        (
            requirement
            for constraint in active_sources
            for requirement in constraint.requirements
            if requirement in active
        ),
        None,
    )
    selected = direct[0] if direct else exact[0][1] if exact else source or base
    candidate = None if selected.url is not None else _exact_version(selected)
    if candidate is not None:
        for requirement in versioned:
            if not requirement.specifier.contains(candidate, prereleases=True):
                raise ConfigurationError(
                    f"Target metadata requirement {requirement!s} excludes the "
                    f"selected {distribution!r} version {candidate}"
                )
    elif len({item.specifier for item in versioned}) > 1:
        raise ConfigurationError(
            f"Target metadata has multiple active ranges for {distribution!r}; "
            "align the ranges or pin the provider"
        )
    extras = set(base.extras)
    extras.update(extra for requirement in active for extra in requirement.extras)
    return _render_requirement(selected, extras)


def effective_studio_requirement(
    launch_requirement: str,
    constraints: Iterable[DependencyConstraint],
    *,
    marker_environment: MarkerEnvironment | None,
) -> str:
    """Resolve the Studio requirement for a concrete target environment."""
    if canonicalize_name(Requirement(launch_requirement).name) != _STUDIO_DISTRIBUTION:
        raise ConfigurationError(
            f"Expected a marimo-studio launch requirement: {launch_requirement!r}"
        )
    return effective_dependency_requirement(
        launch_requirement,
        constraints,
        marker_environment=marker_environment,
    )


def replace_studio_launch_requirement(
    launch_requirements: tuple[str, ...],
    constraints: Iterable[DependencyConstraint],
    *,
    marker_environment: MarkerEnvironment | None,
) -> tuple[str, ...]:
    """Return launch requirements with the effective Studio constraint."""
    selected_constraints = tuple(constraints)
    updated = []
    found = False
    for value in launch_requirements:
        try:
            requirement = Requirement(value)
        except InvalidRequirement as error:
            raise ConfigurationError(
                f"Invalid launch requirement: {value!r}"
            ) from error
        if canonicalize_name(requirement.name) != _STUDIO_DISTRIBUTION:
            updated.append(value)
            continue
        if found:
            raise ConfigurationError("Launch requirements contain marimo-studio twice")
        updated.append(
            effective_studio_requirement(
                value,
                selected_constraints,
                marker_environment=marker_environment,
            )
        )
        found = True
    if not found:
        raise ConfigurationError("Launch requirements omit marimo-studio")
    return tuple(updated)


def allows_source_checkout(
    invoking_version: Version,
    constraints: Iterable[DependencyConstraint],
    *,
    marker_environment: MarkerEnvironment | None,
) -> bool:
    """Return whether the invoking local Studio source satisfies declared ownership."""
    selected_constraints = tuple(constraints)
    if any(
        uses_dependency_source(
            constraint,
            marker_environment=marker_environment,
        )
        for constraint in selected_constraints
    ):
        return False
    active = _active_requirements(selected_constraints, marker_environment)
    if any(requirement.url is not None for requirement in active):
        return False
    exact = {
        version
        for requirement in active
        if (version := _exact_version(requirement)) is not None
    }
    return not exact or exact == {invoking_version}


def bootstrap_launch_requirements(
    *,
    studio_requirement: str,
    provider_ids: Iterable[str],
    bundled_requirements: Mapping[str, str],
    notebook_metadata: Mapping[str, object],
    project_metadata: Mapping[str, object] | None,
    marker_environment: MarkerEnvironment | None,
) -> tuple[str, ...]:
    """Resolve provider bootstrap requirements without loading providers."""
    metadata = (
        (notebook_metadata,)
        if project_metadata is None
        else (
            notebook_metadata,
            project_metadata,
        )
    )
    provider_ids = tuple(sorted(set(provider_ids)))
    studio_base = Requirement(studio_requirement)
    studio_extras = set(studio_base.extras)
    external: set[NormalizedName] = set()
    for provider_id in provider_ids:
        distribution, separator, _registration = provider_id.partition("/")
        if not separator:
            raise ConfigurationError(f"Invalid view provider identity: {provider_id!r}")
        bundled = bundled_requirements.get(provider_id)
        if bundled is not None:
            requirement = Requirement(bundled)
            if canonicalize_name(requirement.name) != _STUDIO_DISTRIBUTION:
                raise ConfigurationError(
                    f"Bundled provider {provider_id!r} has an invalid requirement"
                )
            studio_extras.update(requirement.extras)
            continue
        name = canonicalize_name(distribution)
        if name == _STUDIO_DISTRIBUTION:
            raise ConfigurationError(f"Unknown bundled view provider {provider_id!r}")
        external.add(name)
    studio_base = Requirement(_render_requirement(studio_base, studio_extras))
    studio_constraints = tuple(
        dependency_constraint(document, _STUDIO_DISTRIBUTION) for document in metadata
    )
    resolved = [
        effective_studio_requirement(
            str(studio_base),
            studio_constraints,
            marker_environment=marker_environment,
        )
    ]
    for distribution in sorted(external):
        constraints = tuple(
            dependency_constraint(document, distribution) for document in metadata
        )
        active = _active_requirements(constraints, marker_environment)
        if not active:
            raise ConfigurationError(
                f"Configured provider requires {distribution!r}; add it to the "
                "notebook or project dependencies"
            )
        resolved.append(
            effective_dependency_requirement(
                str(active[0]),
                constraints,
                marker_environment=marker_environment,
                require_declared=True,
            )
        )
    return tuple(resolved)
