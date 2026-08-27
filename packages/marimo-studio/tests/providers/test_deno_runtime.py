"""Exercise provider Deno execution, cache, path, and cancellation ownership."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

from marimo_studio._artifacts.limits import FileBudget
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._filesystem import io as workspace_files
from marimo_studio._processes.provider_runner import ProviderCommandError
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
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno import analysis as _deno_analysis
from marimo_studio.view_providers._bundled._deno import files as _deno_files
from marimo_studio.view_providers._bundled._deno import project as _deno_project
from marimo_studio.view_providers._bundled._deno import runtime as _deno_runtime
from marimo_studio.view_providers._bundled._deno.analysis import (
    InstrumentationEdit,
    apply_instrumentation,
)
from marimo_studio.view_providers._bundled._deno.project import copy_public_assets
from marimo_studio.view_providers._bundled.deno_react import provider as react_provider
from marimo_studio.view_providers._bundled.deno_svelte import (
    provider as svelte_provider,
)

from ..deno_provider_test_support import project as provider_project


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


def test_deno_instrumentation_preserves_ordered_offsets(
    tmp_path: Path,
) -> None:
    relative = PurePosixPath("src/App.tsx")
    source = b"alpha beta gamma"
    edits = (
        InstrumentationEdit(relative, 0, "<start>"),
        InstrumentationEdit(relative, 5, "|"),
        InstrumentationEdit(relative, 10, "<tail>"),
    )
    path = tmp_path.joinpath(*relative.parts)
    path.parent.mkdir(parents=True)
    path.write_bytes(source)

    apply_instrumentation(tmp_path, edits)

    assert path.read_bytes() == b"<start>alpha| beta<tail> gamma"


def test_deno_availability_is_cached_by_binary_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "deno"
    binary.write_bytes(b"deno")
    calls: list[list[str]] = []

    class Supervisor:
        def run(
            self,
            command: list[str],
            _timeout: float,
            **_kwargs: Any,
        ) -> ProcessResult:
            calls.append(command)
            return ProcessResult(0, b"deno 2.9.5\n", b"")

    monkeypatch.setattr(_deno_runtime, "deno_binary", lambda: str(binary))
    monkeypatch.setattr(_deno_runtime, "ProcessSupervisor", Supervisor)
    _deno_runtime._cached_availability.cache_clear()

    assert _deno.deno_availability().available
    assert _deno.deno_availability().available
    binary.write_bytes(b"deno-updated")
    assert _deno.deno_availability().available
    assert calls == [
        [str(binary.resolve()), "--version"],
        [str(binary.resolve()), "--version"],
    ]
    _deno_runtime._cached_availability.cache_clear()


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
    ("provider", "starter"),
    ((react_provider, "react"), (svelte_provider, "svelte")),
)
@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
def test_framework_inspection_preserves_the_project_tree(
    tmp_path: Path,
    provider: Any,
    starter: str,
) -> None:
    root, project = provider_project(tmp_path, provider, starter)
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
    cache_root.parent.parent.mkdir()

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
    assert environment["DENO_DIR"] == str(
        (cache_root / "deno" / _deno.DENO_VERSION).resolve()
    )
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
    assert not (external / _deno.DENO_VERSION).exists()


def test_public_assets_reject_case_equivalent_generated_paths(tmp_path: Path) -> None:
    work = tmp_path / "work"
    output = tmp_path / "output"
    (work / "public").mkdir(parents=True)
    output.mkdir()
    (work / "public" / "logo.svg").write_text("public", encoding="utf-8")
    (output / "Logo.svg").write_text("generated", encoding="utf-8")

    with pytest.raises(ValueError, match="collides with generated output"):
        copy_public_assets(work, output)


def test_deno_inventory_stops_at_the_project_entry_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "view"
    source = root / "src"
    source.mkdir(parents=True)
    for index in range(3):
        (source / f"{index}.ts").write_text(str(index), encoding="utf-8")
    project = ViewProject("view", root, root / "view.toml", "provider", {})
    monkeypatch.setattr(
        _deno_files,
        "PROJECT_INPUT_BUDGET",
        FileBudget(max_files=2, max_file_bytes=1024, max_total_bytes=4096),
    )

    with pytest.raises(ValueError, match="more than 2 entries"):
        _deno.project_inventory(project, ("src",), {".ts": "typescript"})


def test_deno_inventory_applies_one_entry_limit_across_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "view"
    for name in ("first", "second"):
        (root / name / "one").mkdir(parents=True)
        (root / name / "two").mkdir()
    project = ViewProject("view", root, root / "view.toml", "provider", {})
    monkeypatch.setattr(
        _deno_files,
        "PROJECT_INPUT_BUDGET",
        FileBudget(max_files=4, max_file_bytes=1024, max_total_bytes=4096),
    )

    with pytest.raises(ValueError, match="more than 4 entries"):
        _deno.project_inventory(project, ("first", "second"), {})


def test_deno_source_copy_stops_before_a_cancelled_build(tmp_path: Path) -> None:
    root = tmp_path / "view"
    root.mkdir()
    source = root / "src.ts"
    source.write_text("export {};", encoding="utf-8")
    project = ViewProject("view", root, root / "view.toml", "provider", {})
    cancellation = ProviderCancellation()
    cancellation.cancel()
    destination = tmp_path / "work"

    with pytest.raises(ProviderCommandError, match="cancelled"):
        _deno.copy_project_inputs(
            project,
            (PurePosixPath("src.ts"),),
            destination,
            cancellation,
        )

    assert not destination.exists()


def test_public_asset_merge_stops_at_the_combined_output_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    output = tmp_path / "output"
    (work / "public").mkdir(parents=True)
    output.mkdir()
    (output / "index.html").write_text("generated", encoding="utf-8")
    for index in range(2):
        (work / "public" / f"asset-{index}.txt").write_text(
            str(index),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        _deno_project,
        "ARTIFACT_OUTPUT_BUDGET",
        FileBudget(max_files=2, max_file_bytes=1024, max_total_bytes=4096),
    )
    visited = 0
    scan = workspace_files.os.scandir

    class CountingEntries:
        def __init__(self, entries: Any) -> None:
            self._entries = entries

        def __enter__(self) -> CountingEntries:
            self._entries.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._entries.__exit__(*args)

        def __iter__(self) -> CountingEntries:
            return self

        def __next__(self) -> Any:
            nonlocal visited
            entry = next(self._entries)
            visited += 1
            return entry

    def count_entries(path: Any) -> Any:
        entries = scan(path)
        return (
            CountingEntries(entries)
            if Path(path).absolute() == (work / "public").absolute()
            else entries
        )

    monkeypatch.setattr(workspace_files.os, "scandir", count_entries)

    with pytest.raises(ValueError, match="more than 2 entries"):
        copy_public_assets(work, output)

    assert visited == 2
