#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

shopt -s nullglob
wheels=(
	"$root"/dist/marimo_studio-*.whl
	"$root"/dist/from-sdist/marimo_studio-*.whl
)

if [[ "${#wheels[@]}" -ne 2 ]]; then
	printf 'ERROR: Expected the release wheel and one wheel rebuilt from the source distribution\n' >&2
	exit 1
fi

export UV_NO_CONFIG=1

for wheel in "${wheels[@]}"; do
	uv run --no-project --isolated --no-cache --with "$wheel" python - <<'PY'
from importlib.metadata import distribution
import pydoc
import subprocess

import marimo._code_mode as code_mode
import marimo_studio
import marimo_studio.agents as studio_agents
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
assert code_mode.capabilities()["studio"] == "marimo_studio.agents"

plugin = studio_agents.agent_plugin()
skill = studio_agents.agent_skill()
assert plugin.manifest.name == "marimo-studio"
assert plugin.path.name == f"marimo_studio-{dist.version}.agent-plugin"
assert skill in plugin.skills
assert (skill / "SKILL.md").is_file()
assert (skill / "agents" / "openai.yaml").is_file()
assert skill.frontmatter.startswith("name: marimo-studio\n")
help_text = pydoc.render_doc(studio_agents)
assert str(plugin.path) in help_text
assert str(skill / "SKILL.md") in help_text

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
