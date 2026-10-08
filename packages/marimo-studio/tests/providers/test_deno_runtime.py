"""Exercise provider Deno execution, cache, path, and cancellation ownership."""

from __future__ import annotations

import os
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._processes.supervisor import ProcessResult
from marimo_studio._views.inspection import (
    inspect_view_project_sync,
    inspection_request,
)
from marimo_studio.view_providers import (
    ProviderCancellation,
    ProviderCommandResult,
    ViewProject,
)
from marimo_studio.view_providers._builtin import _deno
from marimo_studio.view_providers._builtin._deno import analysis as _deno_analysis
from marimo_studio.view_providers._builtin._deno import cache as _deno_cache
from marimo_studio.view_providers._builtin._deno import runtime as _deno_runtime
from marimo_studio.view_providers._builtin._deno.project import (
    copy_public_assets,
    failure,
)
from marimo_studio.view_providers._builtin.deno_react import provider as react_provider
from marimo_studio.view_providers._builtin.deno_svelte import (
    provider as svelte_provider,
)

from ..deno_provider_test_support import project as provider_project

pytestmark = pytest.mark.deno


def _project_tree(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    entries = []
    for path in sorted(root.rglob("*")):
        kind = "directory" if path.is_dir() else "file"
        content = b"" if path.is_dir() else path.read_bytes()
        entries.append((path.relative_to(root).as_posix(), kind, content))
    return tuple(entries)


def test_deno_analyzer_normalizes_native_windows_paths() -> None:
    assert _deno_analysis.tool_source_path(r"src\App.svelte") == PurePosixPath(
        "src/App.svelte"
    )


def test_provider_inspection_selects_cache_without_mutating_the_project(
    tmp_path: Path,
) -> None:
    root = tmp_path / "view"
    root.mkdir()
    project = ViewProject(
        "view",
        root,
        root / "view.toml",
        "provider",
        {},
    )

    request = inspection_request(project)

    assert request.cache_root == inspection_request(project).cache_root
    assert project.root not in request.cache_root.parents
    assert not request.cache_root.exists()
    assert not artifact_root(project).exists()


@pytest.mark.parametrize(
    ("provider", "provider_id"),
    (
        (react_provider, "marimo-studio/react"),
        (svelte_provider, "marimo-studio/svelte"),
    ),
)
@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_framework_inspection_preserves_the_project_tree(
    tmp_path: Path,
    provider: Any,
    provider_id: str,
) -> None:
    root, project = provider_project(tmp_path, provider, provider_id)
    before = _project_tree(root)

    inspection = inspect_view_project_sync(project)

    assert not [item for item in inspection.diagnostics if item.severity == "error"]
    assert _project_tree(root) == before
    assert not artifact_root(project).exists()


def test_deno_execution_forwards_command_environment_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "view"
    root.mkdir()
    binary = tmp_path / "deno"
    binary.write_bytes(b"deno")
    project = ViewProject(
        "view",
        root,
        root / "view.toml",
        "provider",
        {},
    )
    calls: list[tuple[object, float, Path, dict[str, str]]] = []
    cache_root = tmp_path / "live" / ".artifacts" / ".cache"
    cache_root.mkdir(parents=True)

    class Runner:
        def run(
            self,
            command: object,
            *,
            timeout: float = 120.0,
            **_kwargs: Any,
        ) -> ProviderCommandResult:
            calls.append(
                (
                    command,
                    timeout,
                    cast(Path, _kwargs["cwd"]),
                    cast(dict[str, str], _kwargs["environment"]),
                )
            )
            return ProviderCommandResult(0, "", "")

    monkeypatch.setattr(_deno_runtime, "deno_binary", lambda: str(binary))
    monkeypatch.setattr(_deno_runtime, "distribution_version", lambda _name: "2.10.0")

    execution = _deno.DenoExecution(
        project,
        cache_root=cache_root,
        cancellation=ProviderCancellation(),
        runner=Runner(),
    )
    execution.run(
        ("check", "src/main.ts"),
        cwd=root,
        timeout=30,
        environment={"STUDIO_TEST": "ready"},
    )

    command, timeout, cwd, environment = calls[0]
    assert command == [str(binary), "check", "src/main.ts"]
    assert timeout == 30
    assert cwd == root
    assert environment["DENO_DIR"] == str((cache_root / "deno" / "2.10.0").resolve())
    assert environment["STUDIO_TEST"] == "ready"
    assert cache_root.is_dir()
    assert not (artifact_root(project) / ".cache").exists()


def test_deno_cache_rejects_nested_symlink_before_process_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "snapshot"
    root.mkdir()
    binary = tmp_path / "deno"
    binary.write_bytes(b"deno")
    project = ViewProject(
        "view",
        root,
        root / "view.toml",
        "provider",
        {},
    )
    cache_root = tmp_path / "live" / ".artifacts" / ".cache"
    cache_root.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("outside", encoding="utf-8")
    try:
        (cache_root / "deno").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    process_runs = 0

    class Runner:
        def run(self, *_args: object, **_kwargs: object) -> ProcessResult:
            nonlocal process_runs
            process_runs += 1
            return ProcessResult(0, b"", b"")

    monkeypatch.setattr(_deno_runtime, "deno_binary", lambda: str(binary))

    execution = _deno.DenoExecution(
        project,
        cache_root=cache_root,
        cancellation=ProviderCancellation(),
        runner=cast(Any, Runner()),
    )
    with pytest.raises(
        _deno.DenoExecutionError,
        match=r"regular directory|symlink",
    ):
        execution.run(("check",), cwd=root)

    assert process_runs == 0
    assert sentinel.read_text(encoding="utf-8") == "outside"
    assert not (external / version("deno")).exists()


def test_public_assets_reject_case_equivalent_generated_paths(tmp_path: Path) -> None:
    work = tmp_path / "work"
    output = tmp_path / "output"
    (work / "public").mkdir(parents=True)
    output.mkdir()
    (work / "public" / "logo.svg").write_text("public", encoding="utf-8")
    (output / "Logo.svg").write_text("generated", encoding="utf-8")

    with pytest.raises(ValueError, match="collides with generated output"):
        copy_public_assets(work, output)


def test_public_assets_stop_at_the_published_file_limit(tmp_path: Path) -> None:
    work = tmp_path / "work"
    output = tmp_path / "output"
    (work / "public").mkdir(parents=True)
    (work / "public" / "logo.svg").write_text("public", encoding="utf-8")
    output.mkdir()
    for index in range(4_097):
        (output / f"{index}.js").touch()

    with pytest.raises(ValueError, match="more than 4096 files"):
        copy_public_assets(work, output)


def test_bundle_download_failure_points_to_the_network() -> None:
    diagnostic = failure(
        "React provider",
        "react-build-failed",
        "bundle source",
        "error: failed to download esbuild package tarball @esbuild/linux-x64@0.25.5 "
        "from https://registry.npmjs.org/@esbuild/linux-x64/-/linux-x64-0.25.5.tgz\n"
        "Caused by:\n    0: error reading a body from connection",
    )

    assert "network connection" in diagnostic.hint
    assert "AGENTS.md" not in diagnostic.hint


@pytest.mark.skipif(
    os.name == "nt", reason="Windows creates the cache through path operations"
)
def test_deno_cache_refuses_a_directory_replaced_after_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path.resolve() / "view"
    (project / ".artifacts").mkdir(parents=True)
    outside = tmp_path.resolve() / "outside"
    outside.mkdir()
    cache_root = project / ".artifacts" / ".cache"
    _deno_cache.ensure_cache_directory(cache_root, PurePosixPath("deno"))
    (project / ".artifacts").rename(tmp_path / "previous-artifacts")
    (project / ".artifacts").symlink_to(outside, target_is_directory=True)
    # Another process swaps the directory after Studio resolved the path.
    monkeypatch.setattr(Path, "resolve", lambda path, strict=False: path)

    with pytest.raises(ValueError, match="regular directories"):
        _deno_cache.ensure_cache_directory(cache_root, PurePosixPath("deno"))

    monkeypatch.undo()
    assert list(outside.iterdir()) == []
