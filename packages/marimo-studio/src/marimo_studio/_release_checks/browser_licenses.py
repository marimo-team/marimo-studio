"""Validate browser attribution and installed distribution metadata."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

BROWSER_LICENSE_FILES = (
    "licenses/THIRD_PARTY_NOTICES.json",
    "licenses/THIRD_PARTY_NOTICES.txt",
    "licenses/THIRD_PARTY_LICENSES.txt",
    "licenses/marimo/LICENSE",
    "licenses/marimo-studio/LICENSE",
)
DISTRIBUTION_LICENSE_FILES = ("LICENSE",)
EXACT_RUNTIME_REQUIREMENTS = {
    "agent-plugins": "==0.1.1",
    "tree-sitter": "==0.25.2",
    "tree-sitter-javascript": "==0.25.0",
}
RUNTIME_DEPENDENCY_LICENSES = {
    "tree-sitter": "2019 Max Brunsfeld",
    "tree-sitter-javascript": "2014 Max Brunsfeld",
}
REQUIRED_LICENSE_RECORDS = {
    ("@voidzero-dev/vite-plus-core", "0.2.4"): "MIT",
    ("htmx.org", "2.0.10"): "0BSD",
    ("katex", "0.16.47"): "MIT",
    ("marimo", "0.24.0"): "Apache-2.0",
    ("pyodide", "314.0.0"): "MPL-2.0",
}


def verify_distribution_metadata(distribution_name: str = "marimo-studio") -> None:
    """Validate installed compatibility, dependency, and license metadata."""
    installed = distribution(distribution_name)
    metadata = installed.metadata
    if metadata["License-Expression"] != "Apache-2.0":
        raise AssertionError("Installed package has the wrong license expression")
    if set(metadata.get_all("License-File") or ()) != set(DISTRIBUTION_LICENSE_FILES):
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
    installed_files = tuple(installed.files or ())
    for relative in DISTRIBUTION_LICENSE_FILES:
        suffix = f".dist-info/licenses/{relative}"
        matches = [item for item in installed_files if str(item).endswith(suffix)]
        if len(matches) != 1:
            raise AssertionError(f"Installed package license is missing: {relative}")
        path = Path(str(installed.locate_file(matches[0])))
        if not path.is_file() or not path.read_bytes():
            raise AssertionError(f"Installed package license is empty: {relative}")
    for name, copyright_notice in RUNTIME_DEPENDENCY_LICENSES.items():
        dependency = distribution(name)
        expected_version = EXACT_RUNTIME_REQUIREMENTS[name].removeprefix("==")
        if dependency.version != expected_version:
            raise AssertionError(
                f"Installed {name} version differs from package metadata"
            )
        licenses = [
            item
            for item in (dependency.files or ())
            if str(item).endswith(".dist-info/licenses/LICENSE")
        ]
        if len(licenses) != 1:
            raise AssertionError(f"Installed {name} license is missing")
        text = Path(str(dependency.locate_file(licenses[0]))).read_text(
            encoding="utf-8"
        )
        if "Permission is hereby granted" not in text or copyright_notice not in text:
            raise AssertionError(f"Installed {name} license is unexpected")


def verify_browser_licenses(
    root: Path,
    release: dict[str, object],
    distribution_name: str = "marimo-studio",
) -> None:
    """Validate the exact browser package and license inventory."""
    license_paths = [root / relative for relative in BROWSER_LICENSE_FILES]
    if any(not path.is_file() or not path.read_bytes() for path in license_paths):
        raise AssertionError("Installed browser license inventory is incomplete")
    inventory_value = json.loads(license_paths[0].read_text(encoding="utf-8"))
    if not isinstance(inventory_value, dict) or set(inventory_value) != {
        "schemaVersion",
        "marimo",
        "packages",
        "licenseTexts",
    }:
        raise TypeError("Installed browser license inventory has an invalid shape")
    if inventory_value["schemaVersion"] != 1 or inventory_value["marimo"] != {
        "commit": release["commit"],
        "repository": "https://github.com/marimo-team/marimo.git",
        "version": release["version"],
    }:
        raise AssertionError(
            "Installed browser license inventory has stale Marimo metadata"
        )
    packages = inventory_value["packages"]
    license_texts = inventory_value["licenseTexts"]
    if not isinstance(packages, list) or not packages:
        raise TypeError("Installed browser package inventory is invalid")
    if not isinstance(license_texts, list) or not license_texts:
        raise TypeError("Installed browser license text inventory is invalid")

    coordinates: list[str] = []
    package_digests: set[str] = set()
    records: dict[tuple[str, str], str] = {}
    for package in packages:
        if not isinstance(package, dict) or not {
            "name",
            "version",
            "license",
            "files",
        }.issubset(package):
            raise TypeError("Installed browser package record is invalid")
        name = package["name"]
        package_version = package["version"]
        expression = package["license"]
        files = package["files"]
        if not all(
            isinstance(item, str) and item
            for item in (name, package_version, expression)
        ):
            raise TypeError("Installed browser package identity is invalid")
        if not isinstance(files, list) or not files:
            raise TypeError("Installed browser package license files are invalid")
        coordinate = f"{name}@{package_version}"
        coordinates.append(coordinate)
        records[(name, package_version)] = expression
        file_identities: list[str] = []
        for file in files:
            if not isinstance(file, dict) or set(file) != {
                "name",
                "sha256",
                "source",
            }:
                raise TypeError(
                    f"Installed browser license file is invalid: {coordinate}"
                )
            digest = file["sha256"]
            if (
                not isinstance(file["name"], str)
                or not file["name"]
                or not isinstance(file["source"], str)
                or not file["source"]
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise TypeError(
                    f"Installed browser license file is invalid: {coordinate}"
                )
            file_identities.append(f"{file['name']}:{digest}")
            package_digests.add(digest)
        if file_identities != sorted(set(file_identities)):
            raise AssertionError(
                "Installed browser license files are not sorted and unique: "
                f"{coordinate}"
            )
    if coordinates != sorted(coordinates) or len(coordinates) != len(set(coordinates)):
        raise AssertionError(
            "Installed browser package records are not sorted and unique"
        )

    text_digests: list[str] = []
    text_owners: set[str] = set()
    for text_record in license_texts:
        if not isinstance(text_record, dict) or set(text_record) != {
            "packages",
            "sha256",
            "sources",
        }:
            raise TypeError("Installed browser license text record is invalid")
        digest = text_record["sha256"]
        owners = text_record["packages"]
        sources = text_record["sources"]
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(owners, list)
            or not owners
            or owners != sorted(set(owners))
            or not all(isinstance(item, str) and item for item in owners)
            or not isinstance(sources, list)
            or not sources
            or sources != sorted(set(sources))
            or not all(isinstance(item, str) and item for item in sources)
        ):
            raise TypeError("Installed browser license text record is invalid")
        text_digests.append(digest)
        text_owners.update(owners)
    if text_digests != sorted(set(text_digests)):
        raise AssertionError(
            "Installed browser license texts are not sorted and unique"
        )
    if not package_digests.issubset(text_digests) or not text_owners.issubset(
        coordinates
    ):
        raise AssertionError("Installed browser license references are inconsistent")
    for identity, expression in REQUIRED_LICENSE_RECORDS.items():
        if records.get(identity) != expression:
            raise AssertionError(
                f"Installed browser license record is missing: {identity}"
            )

    marimo_license = root.joinpath("licenses", "marimo", "LICENSE").read_bytes()
    marimo_digest = sha256(marimo_license).hexdigest()
    marimo_record = packages[coordinates.index("marimo@0.24.0")]
    if marimo_digest not in {file["sha256"] for file in marimo_record["files"]}:
        raise AssertionError(
            "Installed Marimo license digest does not match its inventory"
        )
    installed_marimo = distribution("marimo")
    installed_licenses = [
        item
        for item in (installed_marimo.files or ())
        if str(item).endswith(".dist-info/licenses/LICENSE")
    ]
    if (
        len(installed_licenses) != 1
        or marimo_license
        != Path(str(installed_marimo.locate_file(installed_licenses[0]))).read_bytes()
    ):
        raise AssertionError(
            "Installed Marimo license does not match the browser bundle"
        )
    studio_license = root.joinpath("licenses", "marimo-studio", "LICENSE").read_bytes()
    installed_studio = distribution(distribution_name)
    studio_licenses = [
        item
        for item in (installed_studio.files or ())
        if str(item).endswith(".dist-info/licenses/LICENSE")
    ]
    if (
        len(studio_licenses) != 1
        or studio_license
        != Path(str(installed_studio.locate_file(studio_licenses[0]))).read_bytes()
    ):
        raise AssertionError(
            "Installed Studio license does not match the browser bundle"
        )
    license_text = license_paths[2].read_text(encoding="utf-8")
    if not all(digest in license_text for digest in text_digests):
        raise AssertionError("Installed browser license text file is incomplete")
