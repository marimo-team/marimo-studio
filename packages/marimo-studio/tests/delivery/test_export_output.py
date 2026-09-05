from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import marimo_studio._delivery.export as export_module
from marimo_studio._delivery.export import export_view
from marimo_studio._delivery.progress import StaticExportProgress
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.view_owners import load_view_owner, view_owner_path
from marimo_studio.errors import StaticExportError, ViewGenerationConflictError

from .export_test_support import configure_export_view


def _existing_export(notebook: Path, tmp_path: Path) -> Path:
    configure_export_view(notebook)
    output = tmp_path / "site"
    export_view(notebook, output, runtime="wasm")
    return output


def test_export_progress_failure_preserves_the_current_destination(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    expected = output.joinpath("index.html").read_bytes()

    def stop_before_commit(event: StaticExportProgress) -> None:
        if event.event.kind == "commit_started":
            raise RuntimeError("progress consumer stopped")

    with pytest.raises(RuntimeError, match="progress consumer stopped"):
        export_view(
            notebook_path,
            output,
            runtime="wasm",
            force=True,
            progress=stop_before_commit,
        )

    assert output.joinpath("index.html").read_bytes() == expected


def test_export_preserves_a_destination_claimed_while_the_bundle_is_built(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"
    write_bundle = export_module._write_bundle

    def claim_destination(*args: Any, **kwargs: Any) -> int:
        files = write_bundle(*args, **kwargs)
        output.mkdir()
        output.joinpath("concurrent.txt").write_text("keep", encoding="utf-8")
        return files

    monkeypatch.setattr(export_module, "_write_bundle", claim_destination)

    with pytest.raises(StaticExportError) as raised:
        export_view(notebook_path, output, runtime="wasm")

    assert raised.value.code == "destination_changed"
    assert output.joinpath("concurrent.txt").read_text(encoding="utf-8") == "keep"


def test_forced_export_preserves_a_destination_changed_during_generation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    entrypoint = output / "index.html"
    concurrent = b"concurrent export destination edit\n"
    write_bundle = export_module._write_bundle

    def change_destination(*args: Any, **kwargs: Any) -> int:
        files = write_bundle(*args, **kwargs)
        entrypoint.write_bytes(concurrent)
        return files

    monkeypatch.setattr(export_module, "_write_bundle", change_destination)

    with pytest.raises(StaticExportError) as raised:
        export_view(notebook_path, output, runtime="wasm", force=True)

    assert raised.value.code == "destination_changed"
    assert entrypoint.read_bytes() == concurrent


def test_forced_export_preserves_destination_when_view_owner_changes_before_commit(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    expected = output.joinpath("index.html").read_bytes()
    studio = load_studio(notebook_path)
    generation = load_view_owner(studio.view_root, "dashboard").generation
    replacement_generation = "0" * 64 if generation != "0" * 64 else "1" * 64
    owner_path = view_owner_path(studio.view_root, "dashboard")
    write_bundle = export_module._write_bundle

    def replace_owner_after_write(*args: Any, **kwargs: Any) -> int:
        files = write_bundle(*args, **kwargs)
        source = owner_path.read_text(encoding="utf-8")
        owner_path.write_text(
            source.replace(generation, replacement_generation, 1),
            encoding="utf-8",
        )
        return files

    monkeypatch.setattr(export_module, "_write_bundle", replace_owner_after_write)

    with pytest.raises(ViewGenerationConflictError):
        export_view(
            notebook_path,
            output,
            runtime="wasm",
            force=True,
            expected_catalog_generation=studio.catalog_generation,
            expected_generation=studio.view_generations["dashboard"],
        )

    assert output.joinpath("index.html").read_bytes() == expected


def test_export_view_replaces_an_existing_bundle_only_with_force(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    output.joinpath("stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(StaticExportError) as raised:
        export_view(notebook_path, output, runtime="wasm")

    assert raised.value.code == "destination_exists"
    assert "Pass --force" in str(raised.value)

    export_view(notebook_path, output, runtime="wasm", force=True)
    assert not output.joinpath("stale.txt").exists()
    assert output.joinpath("index.html").is_file()


def test_export_rejects_an_existing_output_before_build(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"
    output.mkdir()

    def unexpected_build(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Export built the view before rejecting its output")

    monkeypatch.setattr(export_module, "publish_view", unexpected_build)

    with pytest.raises(StaticExportError) as raised:
        export_view(notebook_path, output, runtime="wasm")

    assert raised.value.code == "destination_exists"


def test_export_creates_missing_destination_parents(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "reports" / "daily" / "site"

    result = export_view(notebook_path, output, runtime="wasm")

    assert result.output == output
    assert result.entrypoint.is_file()


def test_export_reports_a_non_directory_output_parent(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    parent = tmp_path / "not-a-directory"
    parent.write_text("file", encoding="utf-8")

    with pytest.raises(StaticExportError, match="secure static export parent"):
        export_view(
            notebook_path,
            parent / "child" / "site",
            runtime="wasm",
        )


def test_forced_export_protects_authored_namespaces(notebook_path: Path) -> None:
    configure_export_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    protected = (
        ("notebook parent", notebook_path.parent),
        ("configured view", studio.views["executive"].root),
        ("public namespace", notebook_path.parent / "public"),
        ("view catalog", studio.view_root / "future-view"),
    )

    for label, output in protected:
        existed = output.exists()
        try:
            export_view(
                notebook_path,
                output,
                view="dashboard",
                runtime="wasm",
                force=True,
            )
        except StaticExportError as error:
            assert "overlaps a static export source" in str(error), label
        else:
            pytest.fail(f"{label} accepted a destructive static export")

        assert output.exists() is existed, label

    assert notebook_path.is_file()
    assert (studio.views["executive"].root / "view.toml").is_file()
