#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

shopt -s nullglob
wheels=(
	"$root"/dist/marimo_studio-*.whl
	"$root"/dist/from-sdist/marimo_studio-*.whl
)
sdists=("$root"/dist/marimo_studio-*.tar.gz)

if [[ ${#wheels[@]} -ne 2 || ${#sdists[@]} -ne 1 ]]; then
	printf 'ERROR: Expected one wheel, one source distribution, and one rebuilt wheel\n' >&2
	exit 1
fi

direct_wheel="${wheels[0]}"
rebuilt_wheel="${wheels[1]}"
if ! cmp -s "$direct_wheel" "$rebuilt_wheel"; then
	printf 'ERROR: Direct and source-rebuilt wheels differ\n' >&2
	exit 1
fi

plugin_digests="$root/dist/agent-plugin-digests.json"
uv run --frozen python - "$plugin_digests" "${wheels[@]}" "${sdists[@]}" <<'PY'
from hashlib import sha256
from email.parser import BytesParser
import json
from pathlib import Path
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from tarfile import open as open_tar
from zipfile import ZipFile
import sys

digest_path = Path(sys.argv[1])
archives = tuple(Path(value) for value in sys.argv[2:])

root = Path.cwd()
sources = (
    root / "plugin.json",
    *(path for path in sorted((root / "skills" / "marimo-studio").rglob("*")) if path.is_file()),
)
expected = {
    source.relative_to(root).as_posix(): sha256(source.read_bytes()).hexdigest()
    for source in sources
}
package_root = root / "packages" / "marimo-studio"
license_sources = {
    "LICENSE": package_root / "LICENSE",
}
license_bytes = {name: source.read_bytes() for name, source in license_sources.items()}
editor_document = "marimo_studio/_compat/server/editor_document.js"
editor_document_bytes = (package_root / "src" / editor_document).read_bytes()


def packaged(files, read, archive):
    names = [name for name in files if not name.endswith("/")]
    if len(names) != len(set(names)):
        raise AssertionError(f"Distribution contains duplicate paths: {archive}")
    selected = [name for name in names if ".agent-plugin/" in name]
    relative = [name.split(".agent-plugin/", 1)[1] for name in selected]
    if len(relative) != len(set(relative)):
        raise AssertionError(f"Agent Plugin contains duplicate paths: {archive}")
    return {
        path: sha256(read(name)).hexdigest()
        for path, name in zip(relative, selected, strict=True)
    }


def verify_metadata(source, archive):
    metadata = BytesParser().parsebytes(source)
    if metadata["License-Expression"] != "Apache-2.0":
        raise AssertionError(f"Distribution has the wrong license expression: {archive}")
    if set(metadata.get_all("License-File") or ()) != set(license_sources):
        raise AssertionError(f"Distribution has the wrong license files: {archive}")
    if SpecifierSet(metadata["Requires-Python"] or "") != SpecifierSet(">=3.10,<3.15"):
        raise AssertionError(f"Distribution has the wrong Python requirement: {archive}")
    requirements = [Requirement(value) for value in metadata.get_all("Requires-Dist") or ()]
    by_name = {}
    for requirement in requirements:
        by_name.setdefault(canonicalize_name(requirement.name), []).append(requirement)
    for name, specifier in {
        "agent-plugins": ">=0.2",
        "htpy": ">=26.5.1",
        "marimo-export": ">=0.1.0",
        "marimo-lens": ">=0.2.2",
        "tree-sitter": ">=0.25.2",
        "tree-sitter-javascript": ">=0.25.0",
        "watchdog": ">=6.0.0",
    }.items():
        selected = by_name.get(canonicalize_name(name), [])
        if len(selected) != 1 or str(selected[0].specifier) != specifier:
            raise AssertionError(f"Distribution has the wrong {name} requirement: {archive}")

    lens_marker = by_name["marimo-lens"][0].marker
    if (
        lens_marker is None
        or not lens_marker.evaluate({"extra": "lens"})
        or lens_marker.evaluate({"extra": ""})
    ):
        raise AssertionError(f"Distribution must expose Lens through its optional extra: {archive}")


for path in archives:
    if path.suffix == ".whl":
        with ZipFile(path) as archive:
            names = archive.namelist()
            if archive.read(editor_document) != editor_document_bytes:
                raise AssertionError(f"Editor document runtime differs: {path}")
            actual = packaged(names, archive.read, path)
            metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
            metadata_root = metadata_name.removesuffix("METADATA")
            verify_metadata(archive.read(metadata_name), path)
            for relative, expected_bytes in license_bytes.items():
                packaged_bytes = archive.read(f"{metadata_root}licenses/{relative}")
                if packaged_bytes != expected_bytes:
                    raise AssertionError(f"Wheel license differs for {relative}: {path}")
    else:
        with open_tar(path, "r:gz") as archive:
            members = [member for member in archive.getmembers() if member.isfile()]
            names = [member.name for member in members]
            by_name = {member.name: member for member in members}

            def read(name):
                stream = archive.extractfile(by_name[name])
                if stream is None:
                    raise AssertionError(f"Archive file is unreadable: {name}")
                return stream.read()

            actual = packaged(names, read, path)
            distribution_root = names[0].split("/", 1)[0]
            if read(f"{distribution_root}/src/{editor_document}") != editor_document_bytes:
                raise AssertionError(f"Editor document runtime differs: {path}")
            verify_metadata(read(f"{distribution_root}/PKG-INFO"), path)
            for relative, expected_bytes in license_bytes.items():
                packaged_bytes = read(f"{distribution_root}/{relative}")
                if packaged_bytes != expected_bytes:
                    raise AssertionError(f"Source license differs for {relative}: {path}")
    if actual != expected:
        raise AssertionError(
            f"Agent Plugin bytes differ in {path}: "
            f"missing={sorted(expected.keys() - actual.keys())}, "
            f"extra={sorted(actual.keys() - expected.keys())}, "
            f"changed={sorted(key for key in expected.keys() & actual.keys() if expected[key] != actual[key])}"
        )

digest_path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
