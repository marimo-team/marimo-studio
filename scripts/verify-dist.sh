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

if [[ "${#wheels[@]}" -ne 2 ]]; then
	printf 'ERROR: Expected the release wheel and one wheel rebuilt from the source distribution\n' >&2
	exit 1
fi
if [[ "${#sdists[@]}" -ne 1 ]]; then
	printf 'ERROR: Expected one source distribution\n' >&2
	exit 1
fi

STUDIO_SDIST="${sdists[0]}" uv run --frozen python - <<'PY'
from hashlib import sha256
from pathlib import Path
from tarfile import open as open_tar
import os

import agent_plugins

source_root = Path.cwd()
plan = agent_plugins.build_plan(source_root / "packages" / "marimo-studio")
expected = {
    mapping.target.as_posix(): sha256(mapping.source.read_bytes()).hexdigest()
    for mapping in plan.files
}
with open_tar(os.environ["STUDIO_SDIST"], "r:gz") as archive:
    members = [
        member
        for member in archive.getmembers()
        if member.isfile() and "/.agent-plugin/" in member.name
    ]
    paths = [member.name.split("/.agent-plugin/", 1)[1] for member in members]
    assert len(paths) == len(set(paths))
    packaged = {
        path: sha256(archive.extractfile(member).read()).hexdigest()
        for path, member in zip(paths, members, strict=True)
    }
assert packaged == expected
PY

uv run --frozen python - "${wheels[@]}" <<'PY'
from hashlib import sha256
from pathlib import Path
from sys import argv
from zipfile import ZipFile

import agent_plugins

source_root = Path.cwd()
plan = agent_plugins.build_plan(source_root / "packages" / "marimo-studio")
expected = {
    mapping.target.as_posix(): sha256(mapping.source.read_bytes()).hexdigest()
    for mapping in plan.files
}
for wheel in map(Path, argv[1:]):
    with ZipFile(wheel) as archive:
        members = [
            name
            for name in archive.namelist()
            if ".agent-plugin/" in name and not name.endswith("/")
        ]
        paths = [name.split(".agent-plugin/", 1)[1] for name in members]
        assert len(paths) == len(set(paths))
        packaged = {
            path: sha256(archive.read(name)).hexdigest()
            for path, name in zip(paths, members, strict=True)
        }
    assert packaged == expected
PY

export UV_NO_CONFIG=1

for wheel in "${wheels[@]}"; do
	uv run --no-project --isolated --no-cache --with "$wheel" python - <<'PY'
from importlib.metadata import distribution
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import pydoc
import json
import shutil
import subprocess
import tempfile

import agent_plugins
import marimo._code_mode as code_mode
import marimo_studio
import marimo_studio.agent as studio_agent
from marimo_studio._assets import runtime_assets_path

assert marimo_studio.__name__ == "marimo_studio"
dist = distribution("marimo-studio")
entry_points = {(entry.group, entry.name) for entry in dist.entry_points}
assert "agent-plugins==0.1.0" in (dist.requires or ())
assert distribution("agent-plugins").version == "0.1.0"
assert ("console_scripts", "marimo-studio") in entry_points
assert ("marimo.server.asgi.middleware", "marimo-studio") in entry_points
assert ("marimo.kernel.lifespan", "marimo-studio") in entry_points
assert ("marimo.agent.capability", "studio") in entry_points
assert code_mode.capabilities()["studio"] == "marimo_studio.agent"

plugin = studio_agent.agent_plugin()
skill = studio_agent.agent_skill()
assert plugin.manifest.name == "marimo-studio"
assert plugin.path.name == f"marimo_studio-{dist.version}.agent-plugin"
assert skill in plugin.skills
assert (skill / "SKILL.md").is_file()
assert (skill / "agents" / "openai.yaml").is_file()
assert skill.frontmatter.splitlines()[0] == "name: marimo-studio"
help_text = pydoc.render_doc(studio_agent)
assert str(plugin.path) in help_text
assert str(skill / "SKILL.md") in help_text

source_root = Path.cwd()
plan = agent_plugins.build_plan(source_root / "packages" / "marimo-studio")
expected_plugin = {
    mapping.target.as_posix(): sha256(mapping.source.read_bytes()).hexdigest()
    for mapping in plan.files
}
installed_plugin = {
    path.relative_to(plugin.path).as_posix(): sha256(path.read_bytes()).hexdigest()
    for path in plugin.files
}
assert installed_plugin == expected_plugin
assert {
    path.relative_to(skill.path).as_posix()
    for path in skill.files
} == {
    path.relative_to(source_root / "skills" / "marimo-studio").as_posix()
    for path in (source_root / "skills" / "marimo-studio").rglob("*")
    if path.is_file()
}

located = subprocess.run(
    ["agent-plugins", "locate", "marimo-studio"],
    check=True,
    capture_output=True,
    text=True,
)
assert Path(located.stdout.strip()).resolve() == plugin.path.resolve()
listed = subprocess.run(
    ["agent-plugins", "list", "--json"],
    check=True,
    capture_output=True,
    text=True,
)
studio_listing = next(
    item for item in json.loads(listed.stdout)
    if item["distribution"] == "marimo-studio"
)
assert studio_listing == {
    "distribution": "marimo-studio",
    "root": str(plugin.path),
    "skills": [str(skill / "SKILL.md")],
}

with tempfile.TemporaryDirectory() as directory:
    notebook = Path(directory) / "analysis.py"
    shutil.copy(source_root / "apps" / "e2e" / "fixtures" / "plain.py", notebook)
    context = SimpleNamespace(globals={"__file__": str(notebook)})

    def command(*arguments):
        completed = subprocess.run(
            ["marimo-studio", *arguments, "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    assert command("overview", str(notebook)) == studio_agent.overview(context).to_dict()
    assert command("inspect", str(notebook)) == studio_agent.inspect(context).to_dict()
    studio_agent.ensure_view(context, "dashboard")
    assert command("overview", str(notebook)) == studio_agent.overview(context).to_dict()

assets = runtime_assets_path()
for filename in (
    "runtime.js",
    "runtime.css",
    "dev-reload.js",
    "studio.js",
    "studio.css",
    "build-meta.json",
):
    assert (assets / filename).is_file(), filename

assert any((assets / "assets").glob("*worker*.js")), "WebAssembly worker asset"
assert any((assets / "chunks").glob("*.js")), "browser runtime chunks"

result = subprocess.run(
    ["marimo-studio", "--version"],
    check=True,
    capture_output=True,
    text=True,
)
assert result.stdout.strip() == f"marimo-studio, version {dist.version}"
PY
done
