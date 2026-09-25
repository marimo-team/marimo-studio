"""Exercise Svelte analysis, permissions, build, and determinism."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno import vite_project as _vite_build
from marimo_studio.view_providers._bundled.deno_svelte import (
    provider as svelte_provider,
)
from marimo_studio.view_providers._host import provider_registry

from ..deno_provider_test_support import build_provider as _build
from ..deno_provider_test_support import inspect_provider as _inspect
from ..deno_provider_test_support import project as _project
from ..helpers import no_display_notebook_source
from ..provider_test_support import provider_build_request

pytestmark = [
    pytest.mark.deno,
    pytest.mark.usefixtures("shared_deno_test_cache"),
]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_inspection_tracks_literal_site_identity_and_kind(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    source = root / "src" / "App.svelte"
    source.write_text(
        "\ufeff"
        + """<script lang="ts">
  const output = { value: "summary" };
</script>

<div aria-label="😀" mo-value="report.total"></div>
<marimo-output {...output} data-marimo-allow="*"></marimo-output>
<marimo-cell name="controls"></marimo-cell>
""",
        encoding="utf-8",
    )

    inspection = _inspect(svelte_provider, project)

    assert [site.kind for site in inspection.mounts] == [
        "value",
        "output",
        "cell",
    ]
    assert [site.allowed_targets for site in inspection.mounts] == [
        ("report.total",),
        None,
        ("controls",),
    ]
    assert [site.source.line for site in inspection.mounts] == [5, 6, 7]

    source.write_text(
        """<main>
  <div mo-value=" report.total "></div>
  <marimo-cell name=" controls "></marimo-cell>
  <marimo-output value=" summary "></marimo-output>
</main>
""",
        encoding="utf-8",
    )
    padded_sites = _inspect(svelte_provider, project).mounts
    source.write_text(
        """<main>
  <div mo-value="report.total"></div>
  <marimo-cell name="controls"></marimo-cell>
  <marimo-output value="summary"></marimo-output>
</main>
""",
        encoding="utf-8",
    )
    canonical_sites = _inspect(svelte_provider, project).mounts

    assert {site.kind: site.allowed_targets for site in padded_sites} == {
        "cell": ("controls",),
        "output": ("summary",),
        "value": ("report.total",),
    }
    assert {site.kind: site.id for site in padded_sites} == {
        site.kind: site.id for site in canonical_sites
    }

    source.write_text(
        '<marimo-output value="summary" mo-value="summary"></marimo-output>\n',
        encoding="utf-8",
    )
    conflict = _inspect(svelte_provider, project)

    assert [item.code for item in conflict.diagnostics] == ["projection-kind-conflict"]
    assert conflict.mounts == ()


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_default_starter_declares_notebook_cell_targets(
    tmp_path: Path,
) -> None:
    _root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")

    inspection = _inspect(svelte_provider, project)

    assert [(site.kind, site.allowed_targets) for site in inspection.mounts] == [
        ("cell", ("cell-2",)),
    ]


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_keeps_mutated_static_domains_fail_closed(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    (root / "src" / "App.svelte").write_text(
        """<script lang="ts">
  const cells = ["summary"];
  cells.pop();
</script>

{#each cells as name}
  <p>{name}</p>
{:else}
  <marimo-cell name="fallback" data-marimo-studio-site="forged"></marimo-cell>
{/each}
""",
        encoding="utf-8",
    )

    inspection = _inspect(svelte_provider, project)

    assert [item.code for item in inspection.diagnostics] == [
        "projection-site-reserved"
    ]
    assert inspection.mounts == ()


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_starter_builds_without_possible_output_cells(tmp_path: Path) -> None:
    tmp_path = tmp_path / "project, with commas"
    tmp_path.mkdir()
    tmp_path.joinpath("analysis.py").write_text(
        no_display_notebook_source(),
        encoding="utf-8",
    )
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    inspection = _inspect(svelte_provider, project)
    files = root / ".artifacts" / ".staging" / "zero-display" / "files"
    files.mkdir(parents=True)

    report = _build(
        svelte_provider,
        provider_build_request(project, inspection, files),
    )

    assert inspection.diagnostics == ()
    assert inspection.mounts == ()
    assert report.document is not None


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_locates_a_missing_projection_target_in_authored_source(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    (root / "src" / "App.svelte").write_text(
        """<main>
  <marimo-cell target="controls"></marimo-cell>
</main>
""",
        encoding="utf-8",
    )

    diagnostic = _inspect(svelte_provider, project).diagnostics[0]

    assert diagnostic.code == "projection-target-missing"
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("src/App.svelte")


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_each_extracts_bounded_and_wildcard_mounts(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    (root / "src" / "targets.ts").write_text(
        'export const importedCells = [" imported ", "detail", "detail"] as const;\n',
        encoding="utf-8",
    )
    (root / "src" / "App.svelte").write_text(
        """<script lang="ts">
  import { importedCells } from "./targets.ts";

  let runtimeCells = $state<string[]>([]);
  const localCells = [{ name: "overview" }, { name: "detail" }] as const;
  const values = {
    total: " report.total ",
    change: "report.change",
  } as const;
  const outputs = { summary: "summary", table: "detail_table" } as const;
</script>

{#each localCells as item}
  <marimo-cell name={item.name}></marimo-cell>
{/each}
{#each importedCells as name}
  <marimo-cell {name}></marimo-cell>
{/each}
{#each runtimeCells as name}
  <marimo-cell {name} data-marimo-allow="*"></marimo-cell>
{/each}
{#each Object.values(values) as value}
  <strong mo-value={value}></strong>
{/each}
{#each Object.values(outputs) as output}
  <marimo-output value={output}></marimo-output>
{/each}
""",
        encoding="utf-8",
    )

    inspection = _inspect(svelte_provider, project)

    assert [site.kind for site in inspection.mounts] == [
        "cell",
        "cell",
        "cell",
        "value",
        "output",
    ]
    assert [site.allowed_targets for site in inspection.mounts] == [
        ("overview", "detail"),
        ("imported", "detail"),
        None,
        ("report.total", "report.change"),
        ("summary", "detail_table"),
    ]

    source = root / "src" / "App.svelte"
    source.write_text(
        source.read_text(encoding="utf-8").replace(' data-marimo-allow="*"', ""),
        encoding="utf-8",
    )
    diagnostic = next(
        item
        for item in _inspect(svelte_provider, project).diagnostics
        if item.code == "projection-target-unbounded"
    )
    assert diagnostic.source is not None
    assert diagnostic.source.path == PurePosixPath("src/App.svelte")


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_vite_config_cannot_access_paths_outside_staging(
    tmp_path: Path,
) -> None:
    tmp_path = tmp_path / "project, with commas"
    tmp_path.mkdir()
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    external = tmp_path / "external"
    external.mkdir()
    config = root / "vite.config.ts"
    base_config = config.read_text(encoding="utf-8")
    secret = "studio-secret-that-must-not-leak"
    for operation in ("read", "write"):
        target = external / ("secret.txt" if operation == "read" else "owned.txt")
        if operation == "read":
            target.write_text(secret, encoding="utf-8")
            statement = f"readFileSync({json.dumps(str(target))});"
        else:
            statement = f"writeFileSync({json.dumps(str(target))}, 'owned');"
        function = "readFileSync" if operation == "read" else "writeFileSync"
        config.write_text(
            "// @ts-ignore: the denial probe executes this Node compatibility import.\n"
            f'import {{ {function} }} from "node:fs";\n{statement}\n' + base_config,
            encoding="utf-8",
        )
        inspection = _inspect(svelte_provider, project)
        files = root / ".artifacts" / ".staging" / operation / "files"
        files.mkdir(parents=True)

        report = _build(
            svelte_provider,
            provider_build_request(
                project,
                inspection,
                files,
                cache_root=root / ".artifacts" / ".cache",
            ),
        )

        assert report.document is None, operation
        diagnostic = report.diagnostics[0]
        assert diagnostic.code == "svelte-build-failed", operation
        assert secret not in diagnostic.message, operation
        if operation == "write":
            assert not target.exists()


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_vite_config_does_not_inherit_parent_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "studio-parent-secret"
    monkeypatch.setenv("MARIMO_STUDIO_DENIED_SECRET", secret)
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    config = root / "vite.config.ts"
    config.write_text(
        "// @ts-ignore: the denial probe reads the runtime environment.\n"
        "if (process.env.MARIMO_STUDIO_DENIED_SECRET !== undefined) {\n"
        "  throw new Error('parent environment leaked');\n"
        "}\n" + config.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    inspection = _inspect(svelte_provider, project)
    files = root / ".artifacts" / ".staging" / "environment" / "files"
    files.mkdir(parents=True)

    report = _build(
        svelte_provider,
        provider_build_request(
            project,
            inspection,
            files,
            cache_root=root / ".artifacts" / ".cache",
        ),
    )

    assert report.document is not None


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_rejects_unsafe_dependency_configuration_before_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    inspection = _inspect(svelte_provider, project)
    deno_config = root / "deno.json"
    package_config = root / "package.json"
    original = {
        path: path.read_text(encoding="utf-8") for path in (deno_config, package_config)
    }

    def install(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Unsafe dependency configuration reached package installation")

    monkeypatch.setattr(_vite_build, "install_dependencies", install)
    for invalid in ("allow-scripts", "version-range"):
        for path, source in original.items():
            path.write_text(source, encoding="utf-8")
        if invalid == "allow-scripts":
            path = deno_config
            payload = json.loads(original[path])
            payload["allowScripts"] = ["untrusted-package"]
        else:
            path = package_config
            payload = json.loads(original[path])
            payload["devDependencies"]["vite"] = "^8.2.1"
        path.write_text(json.dumps(payload), encoding="utf-8")
        files = root / ".artifacts" / ".staging" / invalid / "files"
        files.mkdir(parents=True)

        report = _build(
            svelte_provider,
            provider_build_request(
                project,
                inspection,
                files,
                cache_root=root / ".artifacts" / ".cache",
            ),
        )

        assert report.document is None, invalid
        assert report.diagnostics[0].code == "svelte-dependencies-invalid", invalid


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_registered_svelte_starter_builds_typed_projections_and_reports_warnings(
    tmp_path: Path,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    (root / "src" / "App.svelte").write_text(
        """<script lang="ts">
  import {
    getMarimoDataSource,
    type MarimoTable,
    observeMarimoValue,
  } from "./lib/marimo-value.ts";

  type Row = { id: string; label: string };

  let rowCount = $state(0);
  const target = "controls";
  const note = (value: unknown) => String(value);
</script>

<span
  hidden
  mo-value="rows"
  use:observeMarimoValue={{
    onValue: (value: MarimoTable<Row>) => {
      rowCount =
        getMarimoDataSource(value)?.bytes.byteLength ?? value.toArray().length;
    },
  }}
></span>
<output>{rowCount}</output>
<div>Visible content</div>
<marimo-cell
  name={target}
  data-note={note(
    /[}>]/.test(">") /* expression comment with > and } */
      ? `escaped \\` > ${target}`
      : '\"quoted >\"'
  )}
></marimo-cell>

<style>
  .unused { color: red; }
</style>
""",
        encoding="utf-8",
    )
    provider = provider_registry().get(project.provider)
    inspection = _inspect(provider, project)
    files = root / ".artifacts" / ".staging" / "build" / "files"
    files.mkdir(parents=True)
    cache_root = tmp_path / "live" / ".artifacts" / ".cache"
    cache_root.parent.mkdir(parents=True)

    report = _build(
        provider,
        provider_build_request(
            project,
            inspection,
            files,
            cache_root=cache_root,
        ),
    )

    instructions = next(
        item
        for item in inspection.editor_documents
        if item.path.as_posix() == "AGENTS.md"
    )
    assert (instructions.language, instructions.access) == ("markdown", "edit")
    assert report.document is not None
    assert "svelte-check-css-unused-selector" in {
        diagnostic.code for diagnostic in report.diagnostics
    }
    javascript = "\n".join(
        path.read_text(encoding="utf-8") for path in files.rglob("*.js")
    )
    assert all(site.id in javascript for site in inspection.mounts)


@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_svelte_revalidates_tsconfig_before_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, project = _project(tmp_path, svelte_provider, "marimo-studio/svelte")
    inspection = _inspect(svelte_provider, project)
    project = replace(project, options={"tsconfig": "../outside.json"})

    def install(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Invalid tsconfig reached package installation")

    monkeypatch.setattr(_vite_build, "install_dependencies", install)
    files = root / ".artifacts" / ".staging" / "invalid-options" / "files"
    files.mkdir(parents=True)

    report = _build(
        svelte_provider,
        provider_build_request(project, inspection, files),
    )

    assert report.document is None
    assert [item.code for item in report.diagnostics] == ["provider-options-invalid"]
    assert "tsconfig" in report.diagnostics[0].message
