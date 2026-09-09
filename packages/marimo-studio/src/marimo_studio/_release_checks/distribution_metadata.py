"""Validate installed distribution metadata."""

from __future__ import annotations

from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

DISTRIBUTION_LICENSE_FILE = "LICENSE"
EXACT_RUNTIME_REQUIREMENTS = {
    "agent-plugins": ">=0.2",
    "htpy": ">=26.5.1",
    "marimo-export": ">=0.0.7",
    "tree-sitter": ">=0.25.2",
    "tree-sitter-javascript": ">=0.25.0",
    "watchdog": ">=6.0.0",
}


def verify_distribution_metadata(distribution_name: str = "marimo-studio") -> None:
    """Validate installed compatibility, dependency, and license metadata."""
    installed = distribution(distribution_name)
    metadata = installed.metadata
    if metadata["License-Expression"] != "Apache-2.0":
        raise AssertionError("Installed package has the wrong license expression")
    if set(metadata.get_all("License-File") or ()) != {DISTRIBUTION_LICENSE_FILE}:
        raise AssertionError("Installed package has the wrong license files")
    if SpecifierSet(metadata["Requires-Python"] or "") != SpecifierSet(">=3.10,<3.15"):
        raise AssertionError("Installed package has the wrong Python requirement")
    requirements = [
        Requirement(value) for value in metadata.get_all("Requires-Dist") or ()
    ]
    by_name: dict[str, list[Requirement]] = {}
    for requirement in requirements:
        by_name.setdefault(canonicalize_name(requirement.name), []).append(requirement)
    for name, specifier in EXACT_RUNTIME_REQUIREMENTS.items():
        selected = by_name.get(canonicalize_name(name), [])
        if len(selected) != 1 or str(selected[0].specifier) != specifier:
            raise AssertionError(f"Installed package has the wrong {name} requirement")
    suffix = f".dist-info/licenses/{DISTRIBUTION_LICENSE_FILE}"
    matches = [item for item in installed.files or () if str(item).endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(
            f"Installed package license is missing: {DISTRIBUTION_LICENSE_FILE}"
        )
    path = Path(str(installed.locate_file(matches[0])))
    if not path.is_file() or not path.read_bytes():
        raise AssertionError(
            f"Installed package license is empty: {DISTRIBUTION_LICENSE_FILE}"
        )
