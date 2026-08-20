"""Validate Studio's coordinated marimo-export dependency sources."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - contributor Python 3.10
    import tomli as tomllib

PUBLIC_NPM_PACKAGES = (
    "@marimo-team/marimo-export",
    "@marimo-team/portable-json",
)
LOCAL_SOURCE_PREFIXES = ("file:", "link:", "workspace:")
PYPI_INDEX = "https://pypi.org/simple"
PYPI_FILES_HOST = "files.pythonhosted.org"
NPM_REGISTRY_HOST = "registry.npmjs.org"
YAML_MAPPING = re.compile(
    r"^(?P<indent> *)(?P<key>\"(?:\\.|[^\"])*\"|'(?:''|[^'])*'|[^:]+):(?P<value>.*)$"
)


@dataclass(frozen=True)
class LockedPythonArtifact:
    url: str
    sha256: str


@dataclass(frozen=True)
class ReleaseLocks:
    python_artifacts: tuple[LockedPythonArtifact, ...]
    npm_integrities: tuple[tuple[str, str], ...]


JsonFetcher = Callable[[str, str], Any]


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _studio_metadata(root: Path) -> dict[str, Any]:
    return _load_toml(root / "packages/marimo-studio/pyproject.toml")["project"]


def _python_requirement(project: dict[str, Any]) -> str:
    requirements = [
        value for value in project["dependencies"] if value.startswith("marimo-export")
    ]
    if len(requirements) != 1:
        raise RuntimeError(
            f"marimo-studio must contain one exact marimo-export pin: {requirements}"
        )
    match = re.fullmatch(r"marimo-export==([0-9]+\.[0-9]+\.[0-9]+)", requirements[0])
    if match is None:
        raise RuntimeError(
            f"marimo-studio must use an exact marimo-export X.Y.Z pin: {requirements}"
        )
    return match.group(1)


def _linked_python_version(root: Path, version: str, *, release: bool) -> None:
    workspace = _load_toml(root / "pyproject.toml")
    source = (
        workspace.get("tool", {}).get("uv", {}).get("sources", {}).get("marimo-export")
    )
    if source is None:
        return
    if release:
        raise RuntimeError("release mode rejects the editable marimo-export uv source")
    if not isinstance(source, dict) or source.get("editable") is not True:
        raise RuntimeError("the development marimo-export uv source must be editable")
    path = source.get("path")
    if not isinstance(path, str):
        raise TypeError("the development marimo-export uv source must contain a path")
    linked = (root / path / "pyproject.toml").resolve()
    project = _load_toml(linked)["project"]
    if project.get("name") != "marimo-export" or project.get("version") != version:
        raise RuntimeError(
            f"the linked Python package must be marimo-export {version}: {linked}"
        )


def _package_manifests(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for parent in (root / "apps", root / "packages")
            for path in parent.glob("*/package.json")
        )
    )


def _javascript_dependencies(root: Path, version: str, *, release: bool) -> None:
    found: dict[str, int] = {name: 0 for name in PUBLIC_NPM_PACKAGES}
    for manifest_path in _package_manifests(root):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dependencies = {
            **manifest.get("dependencies", {}),
            **manifest.get("optionalDependencies", {}),
            **manifest.get("peerDependencies", {}),
        }
        for name in PUBLIC_NPM_PACKAGES:
            if name not in dependencies:
                continue
            found[name] += 1
            source = dependencies[name]
            if source == version:
                continue
            if release or not isinstance(source, str) or not source.startswith("link:"):
                raise RuntimeError(
                    f"{manifest_path.relative_to(root)} must use exact {name} {version} "
                    f"in release mode, observed {source!r}"
                )
            linked_manifest = (
                manifest_path.parent / source.removeprefix("link:") / "package.json"
            )
            linked = json.loads(linked_manifest.resolve().read_text(encoding="utf-8"))
            if linked.get("name") != name or linked.get("version") != version:
                raise RuntimeError(
                    f"{manifest_path.relative_to(root)} links to unexpected {name} metadata"
                )
    missing = [name for name, count in found.items() if count == 0]
    if missing:
        raise RuntimeError(f"Studio has no dependency on public package {missing[0]}")


def _yaml_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        decoded = json.loads(value)
        if not isinstance(decoded, str):
            raise TypeError(f"expected a YAML string, observed {decoded!r}")
        return decoded
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _yaml_mapping(line: str) -> tuple[int, str, str] | None:
    match = YAML_MAPPING.fullmatch(line.rstrip())
    if match is None:
        return None
    return (
        len(match.group("indent")),
        _yaml_scalar(match.group("key")),
        _yaml_scalar(match.group("value")),
    )


def _pnpm_importer_dependencies(
    text: str,
) -> dict[str, list[dict[str, str]]]:
    dependencies: dict[str, list[dict[str, str]]] = {}
    section = ""
    dependency_group = ""
    package_name = ""
    for line in text.splitlines():
        entry = _yaml_mapping(line)
        if entry is None:
            continue
        indent, key, value = entry
        if indent == 0:
            section = key
            dependency_group = ""
            package_name = ""
            continue
        if section != "importers":
            continue
        if indent == 2:
            dependency_group = ""
            package_name = ""
        elif indent == 4:
            dependency_group = (
                key
                if key in {"dependencies", "devDependencies", "optionalDependencies"}
                else ""
            )
            package_name = ""
        elif indent == 6 and dependency_group:
            package_name = key
            dependencies.setdefault(package_name, []).append({})
        elif indent == 8 and package_name and key in {"specifier", "version"}:
            dependencies[package_name][-1][key] = value
    return dependencies


def _inline_mapping_value(value: str, key: str) -> str | None:
    match = re.search(rf"(?:^|[{{,])\s*{re.escape(key)}:\s*([^,}}]+)", value)
    return _yaml_scalar(match.group(1)) if match is not None else None


def _pnpm_package_resolutions(text: str) -> dict[str, dict[str, str]]:
    resolutions: dict[str, dict[str, str]] = {}
    section = ""
    package = ""
    for line in text.splitlines():
        entry = _yaml_mapping(line)
        if entry is None:
            continue
        indent, key, value = entry
        if indent == 0:
            section = key
            package = ""
            continue
        if section != "packages":
            continue
        if indent == 2:
            package = key
            continue
        if not package:
            continue
        if indent == 4 and key == "resolution":
            resolution = resolutions.setdefault(package, {})
            for field in ("integrity", "tarball"):
                observed = _inline_mapping_value(value, field)
                if observed is not None:
                    resolution[field] = observed
        elif indent >= 6 and key in {"integrity", "tarball"}:
            resolutions.setdefault(package, {})[key] = value
    return resolutions


def _workspace_release_age_exclusions(root: Path) -> tuple[str, ...]:
    exclusions: list[str] = []
    active = False
    for line in (root / "pnpm-workspace.yaml").read_text(encoding="utf-8").splitlines():
        if line == "minimumReleaseAgeExclude:":
            active = True
            continue
        if not active:
            continue
        if line.startswith("  - "):
            exclusions.append(_yaml_scalar(line.removeprefix("  - ")))
            continue
        if line and not line.startswith(" "):
            break
    return tuple(exclusions)


def _workspace_policy(root: Path, version: str) -> None:
    observed = tuple(
        value
        for value in _workspace_release_age_exclusions(root)
        if value.startswith("@marimo-team/")
    )
    expected = tuple(f"{name}@{version}" for name in PUBLIC_NPM_PACKAGES)
    if len(observed) != len(expected) or set(observed) != set(expected):
        raise RuntimeError(
            "pnpm-workspace.yaml must exempt the exact coordinated npm releases: "
            f"{expected}"
        )


def _canonical_url(url: str, host: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == host
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _locked_python_artifacts(
    package: dict[str, Any],
) -> tuple[LockedPythonArtifact, ...]:
    records: list[Any] = [package.get("sdist"), *package.get("wheels", [])]
    artifacts: list[LockedPythonArtifact] = []
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("uv.lock must record the marimo-export sdist and wheels")
        url = record.get("url")
        digest = record.get("hash")
        if not isinstance(url, str) or not _canonical_url(url, PYPI_FILES_HOST):
            raise RuntimeError(
                "uv.lock must resolve marimo-export artifacts from files.pythonhosted.org"
            )
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError("uv.lock must record each marimo-export SHA-256")
        artifacts.append(
            LockedPythonArtifact(url=url, sha256=digest.removeprefix("sha256:"))
        )
    if len(artifacts) < 2:
        raise RuntimeError("uv.lock must record the marimo-export sdist and wheels")
    return tuple(artifacts)


def _sha512_integrity(value: str) -> bool:
    if not value.startswith("sha512-"):
        return False
    try:
        return len(base64.b64decode(value.removeprefix("sha512-"), validate=True)) == 64
    except (binascii.Error, ValueError):
        return False


def _release_locks(root: Path, version: str) -> ReleaseLocks:
    lock = _load_toml(root / "uv.lock")
    packages = [
        package for package in lock["package"] if package.get("name") == "marimo-export"
    ]
    if len(packages) != 1:
        raise RuntimeError("uv.lock must contain one marimo-export package")
    package = packages[0]
    if package.get("version") != version or package.get("source") != {
        "registry": PYPI_INDEX
    }:
        raise RuntimeError(
            f"uv.lock must resolve marimo-export {version} from {PYPI_INDEX}"
        )
    python_artifacts = _locked_python_artifacts(package)

    pnpm_text = (root / "pnpm-lock.yaml").read_text(encoding="utf-8")
    importer_dependencies = _pnpm_importer_dependencies(pnpm_text)
    package_resolutions = _pnpm_package_resolutions(pnpm_text)
    observed: dict[str, int] = {name: 0 for name in PUBLIC_NPM_PACKAGES}
    npm_integrities: dict[str, set[str]] = {name: set() for name in PUBLIC_NPM_PACKAGES}
    for name in PUBLIC_NPM_PACKAGES:
        for record in importer_dependencies.get(name, []):
            observed[name] += 1
            if record.get("specifier") != version:
                raise RuntimeError(f"pnpm-lock.yaml must pin {name} to {version}")
            resolved = record.get("version", "")
            resolved_match = re.fullmatch(
                rf"(?P<base>{re.escape(version)})(?:\(.+\))?", resolved
            )
            if resolved.startswith(LOCAL_SOURCE_PREFIXES) or resolved_match is None:
                raise RuntimeError(
                    f"pnpm-lock.yaml must resolve public {name} {version}"
                )
            package_key = f"{name}@{resolved_match.group('base')}"
            resolution = package_resolutions.get(package_key, {})
            integrity = resolution.get("integrity")
            if integrity is None or not _sha512_integrity(integrity):
                raise RuntimeError(
                    f"pnpm-lock.yaml must record the registry integrity for {name} {version}"
                )
            tarball = resolution.get("tarball")
            if tarball is not None and not _canonical_npm_tarball(
                tarball, name, version
            ):
                raise RuntimeError(
                    f"pnpm-lock.yaml must use the canonical npm tarball for {name} {version}"
                )
            npm_integrities[name].add(integrity)
    missing = [name for name, count in observed.items() if count == 0]
    if missing:
        raise RuntimeError(f"pnpm-lock.yaml does not resolve {missing[0]}")
    conflicting = [
        name for name, integrities in npm_integrities.items() if len(integrities) != 1
    ]
    if conflicting:
        raise RuntimeError(
            f"pnpm-lock.yaml must use one registry integrity for {conflicting[0]}"
        )
    return ReleaseLocks(
        python_artifacts=python_artifacts,
        npm_integrities=tuple(
            (name, next(iter(npm_integrities[name]))) for name in PUBLIC_NPM_PACKAGES
        ),
    )


def _public_json(url: str, label: str) -> Any:
    try:
        with urlopen(url, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"{label} returned HTTP {response.status}")
            if response.geturl() != url:
                raise RuntimeError(
                    f"{label} redirected away from its canonical registry URL"
                )
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"{label} is unavailable at the public registry") from error
    except (TimeoutError, URLError) as error:
        raise RuntimeError(
            f"{label} could not be verified before dependency installation: {error}"
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{label} returned invalid registry metadata") from error


def _metadata_object(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError(f"{label} returned invalid registry metadata")
    return payload


def _public_python_version(
    version: str, locks: ReleaseLocks, fetch_json: JsonFetcher
) -> None:
    label = f"marimo-export {version}"
    url = f"https://pypi.org/pypi/marimo-export/{version}/json"
    metadata = _metadata_object(fetch_json(url, label), label)
    info = metadata.get("info")
    if (
        not isinstance(info, dict)
        or info.get("name") != "marimo-export"
        or info.get("version") != version
    ):
        raise RuntimeError(f"{label} returned unexpected PyPI metadata")
    urls = metadata.get("urls")
    if not isinstance(urls, list) or not urls:
        raise RuntimeError(f"{label} has no public PyPI artifacts")
    public_artifacts: dict[str, str] = {}
    for record in urls:
        if not isinstance(record, dict):
            raise TypeError(f"{label} returned invalid PyPI artifact metadata")
        artifact_url = record.get("url")
        digests = record.get("digests")
        sha256 = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(artifact_url, str) or not _canonical_url(
            artifact_url, PYPI_FILES_HOST
        ):
            raise RuntimeError(
                f"{label} metadata must use files.pythonhosted.org artifacts"
            )
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise RuntimeError(f"{label} metadata must provide artifact SHA-256 values")
        previous = public_artifacts.setdefault(artifact_url, sha256)
        if previous != sha256:
            raise RuntimeError(f"{label} returned conflicting artifact SHA-256 values")
    for artifact in locks.python_artifacts:
        if public_artifacts.get(artifact.url) != artifact.sha256:
            raise RuntimeError(
                f"uv.lock SHA-256 does not match public PyPI metadata for {artifact.url}"
            )


def _canonical_npm_tarball(url: str, name: str, version: str) -> bool:
    if not _canonical_url(url, NPM_REGISTRY_HOST):
        return False
    path = unquote(urlsplit(url).path)
    package_basename = name.rsplit("/", maxsplit=1)[-1]
    return path == f"/{name}/-/{package_basename}-{version}.tgz"


def _public_npm_version(
    name: str,
    version: str,
    locked_integrity: str,
    fetch_json: JsonFetcher,
) -> None:
    label = f"{name} {version}"
    encoded = quote(name, safe="")
    url = f"https://registry.npmjs.org/{encoded}/{version}"
    metadata = _metadata_object(fetch_json(url, label), label)
    if metadata.get("name") != name or metadata.get("version") != version:
        raise RuntimeError(f"{label} returned unexpected npm metadata")
    dist = metadata.get("dist")
    tarball = dist.get("tarball") if isinstance(dist, dict) else None
    integrity = dist.get("integrity") if isinstance(dist, dict) else None
    if not isinstance(tarball, str) or not _canonical_npm_tarball(
        tarball, name, version
    ):
        raise RuntimeError(f"{label} metadata must use its canonical npm tarball")
    if integrity != locked_integrity:
        raise RuntimeError(
            f"pnpm-lock.yaml integrity does not match public npm metadata for {label}"
        )


def _public_versions(
    version: str,
    locks: ReleaseLocks,
    *,
    fetch_json: JsonFetcher = _public_json,
) -> None:
    _public_python_version(version, locks, fetch_json)
    npm_integrities = dict(locks.npm_integrities)
    for name in PUBLIC_NPM_PACKAGES:
        _public_npm_version(name, version, npm_integrities[name], fetch_json)


def check(
    root: Path,
    *,
    release: bool,
    public: bool,
    fetch_json: JsonFetcher = _public_json,
) -> None:
    project = _studio_metadata(root)
    studio_version = project.get("version")
    if (
        not isinstance(studio_version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", studio_version) is None
    ):
        raise RuntimeError("marimo-studio must use a final X.Y.Z version")
    export_version = _python_requirement(project)
    _workspace_policy(root, export_version)
    _linked_python_version(root, export_version, release=release)
    _javascript_dependencies(root, export_version, release=release)
    release_locks = None
    if release:
        release_locks = _release_locks(root, export_version)
    if public:
        if not release:
            raise RuntimeError("public dependency checks require release mode")
        if release_locks is None:
            raise RuntimeError("public dependency checks require release lock metadata")
        _public_versions(export_version, release_locks, fetch_json=fetch_json)
    mode = "public release" if public else "release" if release else "development"
    print(
        f"Verified Studio {studio_version} {mode} dependencies for "
        f"marimo-export {export_version}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release", action="store_true", help="require registry-only sources"
    )
    parser.add_argument(
        "--public", action="store_true", help="require public registry versions"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="marimo-studio repository root",
    )
    arguments = parser.parse_args()
    try:
        check(
            arguments.root.resolve(), release=arguments.release, public=arguments.public
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
