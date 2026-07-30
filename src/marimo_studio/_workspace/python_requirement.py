"""Intersect notebook and package Python requirements."""

from __future__ import annotations

from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from marimo_studio.errors import ConfigurationError, DependencyError


@dataclass(frozen=True)
class _Bound:
    version: Version
    inclusive: bool


def _stronger_lower(current: _Bound | None, candidate: _Bound) -> _Bound:
    if current is None or candidate.version > current.version:
        return candidate
    if candidate.version == current.version and not candidate.inclusive:
        return candidate
    return current


def _stronger_upper(current: _Bound | None, candidate: _Bound) -> _Bound:
    if current is None or candidate.version < current.version:
        return candidate
    if candidate.version == current.version and not candidate.inclusive:
        return candidate
    return current


def _wildcard_bounds(version: str) -> tuple[_Bound, _Bound]:
    release = tuple(int(part) for part in version.removesuffix(".*").split("."))
    lower = Version(".".join(map(str, release)))
    upper = Version(".".join(map(str, (*release[:-1], release[-1] + 1))))
    return _Bound(lower, True), _Bound(upper, False)


def _compatible_bounds(version: str) -> tuple[_Bound, _Bound]:
    lower = Version(version)
    prefix = lower.release[:-1]
    upper = Version(".".join(map(str, (*prefix[:-1], prefix[-1] + 1))))
    return _Bound(lower, True), _Bound(upper, False)


def _interval_is_excluded(
    lower: _Bound,
    upper: _Bound,
    exclusions: list[tuple[_Bound, _Bound]],
) -> bool:
    cursor = lower.version
    included = lower.inclusive
    for excluded_lower, excluded_upper in sorted(
        exclusions,
        key=lambda item: item[0].version,
    ):
        if excluded_upper.version < cursor:
            continue
        if excluded_lower.version > cursor:
            return False
        if (
            excluded_lower.version == cursor
            and included
            and not excluded_lower.inclusive
        ):
            return False
        if excluded_upper.version > cursor:
            cursor = excluded_upper.version
            included = not excluded_upper.inclusive
        if cursor > upper.version:
            return True
        if cursor == upper.version and (not upper.inclusive or not included):
            return True
    return False


def _is_empty(
    combined: SpecifierSet,
    specifiers: tuple[Specifier, ...],
) -> bool:
    lower: _Bound | None = None
    upper: _Bound | None = None
    exact: set[Version] = set()
    exclusions: list[tuple[_Bound, _Bound]] = []
    for specifier in specifiers:
        operator = specifier.operator
        raw = specifier.version
        try:
            if operator == "==" and raw.endswith(".*"):
                candidate_lower, candidate_upper = _wildcard_bounds(raw)
                lower = _stronger_lower(lower, candidate_lower)
                upper = _stronger_upper(upper, candidate_upper)
            elif operator in {"==", "==="}:
                exact.add(Version(raw))
            elif operator == "!=" and raw.endswith(".*"):
                exclusions.append(_wildcard_bounds(raw))
            elif operator == "~=":
                candidate_lower, candidate_upper = _compatible_bounds(raw)
                lower = _stronger_lower(lower, candidate_lower)
                upper = _stronger_upper(upper, candidate_upper)
            elif operator in {">", ">="}:
                lower = _stronger_lower(
                    lower,
                    _Bound(Version(raw), operator == ">="),
                )
            elif operator in {"<", "<="}:
                upper = _stronger_upper(
                    upper,
                    _Bound(Version(raw), operator == "<="),
                )
        except (InvalidVersion, ValueError) as error:
            raise ConfigurationError(
                f"Invalid requires-python constraint: {specifier}"
            ) from error
    if exact:
        return not any(
            combined.contains(candidate, prereleases=True) for candidate in exact
        )
    if lower is None or upper is None:
        return False
    if lower.version > upper.version:
        return True
    if lower.version < upper.version:
        return _interval_is_excluded(lower, upper, exclusions)
    if not lower.inclusive or not upper.inclusive:
        return True
    return not combined.contains(lower.version, prereleases=True)


def _compact(specifiers: tuple[Specifier, ...]) -> str:
    lower: Specifier | None = None
    upper: Specifier | None = None
    others: dict[str, Specifier] = {}
    for specifier in specifiers:
        if specifier.operator in {">", ">="}:
            if lower is None:
                lower = specifier
                continue
            candidate = Version(specifier.version)
            selected = Version(lower.version)
            if candidate > selected or (
                candidate == selected
                and specifier.operator == ">"
                and lower.operator == ">="
            ):
                lower = specifier
            continue
        if specifier.operator in {"<", "<="}:
            if upper is None:
                upper = specifier
                continue
            candidate = Version(specifier.version)
            selected = Version(upper.version)
            if candidate < selected or (
                candidate == selected
                and specifier.operator == "<"
                and upper.operator == "<="
            ):
                upper = specifier
            continue
        others[str(specifier)] = specifier
    ordered = [item for item in (lower, upper) if item is not None]
    ordered.extend(others[key] for key in sorted(others))
    return ",".join(map(str, ordered))


def intersect_python_requirements(
    notebook_requirement: str,
    package_requirement: str,
) -> str:
    """Return the satisfiable intersection of two PEP 440 specifier sets."""
    try:
        combined = SpecifierSet(",".join((notebook_requirement, package_requirement)))
    except InvalidSpecifier as error:
        raise ConfigurationError(
            f"Invalid requires-python constraint: {error}"
        ) from error
    specifiers = tuple(combined)
    if _is_empty(combined, specifiers):
        raise DependencyError(
            "The notebook and marimo-studio Python requirements do not overlap: "
            f"{notebook_requirement!r} and {package_requirement!r}"
        )
    return _compact(specifiers)
