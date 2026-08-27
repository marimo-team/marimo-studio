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

for archive in "${wheels[@]}" "${sdists[@]}"; do
	if [[ "$(wc -c <"$archive")" -gt $((8 * 1024 * 1024)) ]]; then
		printf 'ERROR: Distribution exceeds the 8 MiB release budget: %s\n' "$archive" >&2
		exit 1
	fi
done

plugin_digests="$root/dist/agent-plugin-digests.json"
uv run --frozen python - "$plugin_digests" "${wheels[@]}" "${sdists[@]}" <<'PY'
from hashlib import sha256
import json
from pathlib import Path
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


for path in archives:
    if path.suffix == ".whl":
        with ZipFile(path) as archive:
            actual = packaged(archive.namelist(), archive.read, path)
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
    if actual != expected:
        raise AssertionError(
            f"Agent Plugin bytes differ in {path}: "
            f"missing={sorted(expected.keys() - actual.keys())}, "
            f"extra={sorted(actual.keys() - expected.keys())}, "
            f"changed={sorted(key for key in expected.keys() & actual.keys() if expected[key] != actual[key])}"
        )

digest_path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

package_version="$(uv run --frozen python - "${wheels[@]}" <<'PY'
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile
import sys

versions = set()
for value in sys.argv[1:]:
    with ZipFile(Path(value)) as wheel:
        metadata = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        versions.add(BytesParser().parsebytes(wheel.read(metadata))["Version"])
if len(versions) != 1:
    raise SystemExit(f"Built wheels disagree on version: {sorted(versions)}")
print(versions.pop())
PY
)"

uv run --no-project --isolated --no-cache \
	--with "$direct_wheel" \
	--with "agent-plugins==0.1.0" \
	python scripts/verify-installed-package.py \
	--expected-version "$package_version" \
	--expected-plugin-digests "$plugin_digests"
uv run --no-project --isolated --no-cache --no-sources-package marimo-studio \
	--with "$direct_wheel" \
	--with "$root/apps/e2e/fixtures-provider/provider" \
	--with "ty==0.0.69" \
	python scripts/verify-external-provider.py --typecheck
uv run --no-project --isolated --no-cache \
	--with "${direct_wheel}[deno]" \
	--with "agent-plugins==0.1.0" \
	python scripts/verify-installed-package.py \
	--expected-version "$package_version" \
	--expected-plugin-digests "$plugin_digests" \
	--deno
