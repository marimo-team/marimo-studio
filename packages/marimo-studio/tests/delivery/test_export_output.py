from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import marimo_studio._delivery.export as export_module
import marimo_studio._delivery.export_output as output_module
import marimo_studio._filesystem._secure_rename as secure_rename
from marimo_studio._delivery.export import export_view
from marimo_studio._filesystem.paths import PORTABLE_PATH_COMPONENT_MAX_BYTES
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.view_owners import load_view_owner, view_owner_path
from marimo_studio.errors import StaticExportError, ViewGenerationConflictError

from .export_test_support import configure_export_view


@pytest.mark.parametrize(
    "force",
    (False, True),
    ids=("new-destination", "forced-replacement"),
)
def test_export_supports_a_max_component_destination(
    notebook_path: Path,
    tmp_path: Path,
    force: bool,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / ("s" * PORTABLE_PATH_COMPONENT_MAX_BYTES)
    if force:
        output.mkdir()
        output.joinpath("previous.txt").write_text("previous", encoding="utf-8")

    result = export_view(notebook_path, output, force=force)

    assert result.output == output
    assert output.joinpath("index.html").is_file()
    if force:
        assert not output.joinpath("previous.txt").exists()
    assert not tuple(tmp_path.glob(".marimo-studio-export-*"))


def _existing_export(notebook: Path, tmp_path: Path) -> Path:
    configure_export_view(notebook)
    output = tmp_path / "site"
    export_view(notebook, output)
    return output


def test_export_view_preserves_a_destination_created_during_generation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    output = tmp_path / "site"
    commit_bundle = export_module._commit_bundle

    def create_destination(
        staged: Path,
        target: output_module.OutputTarget,
    ) -> None:
        output.mkdir()
        output.joinpath("concurrent.txt").write_text("keep", encoding="utf-8")
        commit_bundle(staged, target)

    monkeypatch.setattr(export_module, "_commit_bundle", create_destination)

    with pytest.raises(StaticExportError, match="Output changed"):
        export_view(notebook_path, output)

    assert output.joinpath("concurrent.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_export_rejects_an_absent_output_after_its_parent_is_replaced(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_export_view(notebook_path)
    parent = tmp_path / "safe-parent"
    parent.mkdir()
    retired = tmp_path / "retired-parent"
    outside = tmp_path / "outside"
    outside.mkdir()
    output = parent / "site"
    commit_bundle = export_module._commit_bundle

    def replace_parent(
        staged: Path,
        target: output_module.OutputTarget,
    ) -> None:
        parent.rename(retired)
        parent.symlink_to(outside, target_is_directory=True)
        commit_bundle(staged, target)

    monkeypatch.setattr(export_module, "_commit_bundle", replace_parent)

    with pytest.raises(StaticExportError, match="Output parent changed"):
        export_view(notebook_path, output)

    assert not (outside / "site").exists()
    assert not (retired / "site").exists()


def test_export_preserves_an_absent_output_claimed_during_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "site"
    staged = tmp_path / "bundle"
    staged.mkdir()
    staged.joinpath("index.html").write_text("new", encoding="utf-8")

    with secure_directory(tmp_path) as filesystem:
        target = output_module.OutputTarget(output, None, filesystem)
        rename = filesystem.rename_if_absent

        def claim_then_rename(source: Path, destination: Path) -> None:
            destination.mkdir()
            rename(source, destination)

        monkeypatch.setattr(filesystem, "rename_if_absent", claim_then_rename)

        with pytest.raises(StaticExportError, match="Output changed"):
            output_module.commit_bundle(staged, target)

    assert output.is_dir() and not tuple(output.iterdir())
    assert staged.joinpath("index.html").read_text(encoding="utf-8") == "new"


def test_forced_export_preserves_a_destination_changed_during_generation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    entrypoint = output / "index.html"
    concurrent = b"concurrent export destination edit\n"
    commit_bundle = export_module._commit_bundle

    def change_destination(
        staged: Path,
        target: output_module.OutputTarget,
    ) -> None:
        entrypoint.write_bytes(concurrent)
        commit_bundle(staged, target)

    monkeypatch.setattr(export_module, "_commit_bundle", change_destination)

    with pytest.raises(StaticExportError, match="Output changed"):
        export_view(notebook_path, output, force=True)

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
            force=True,
            expected_catalog_generation=studio.catalog_generation,
            expected_generation=studio.view_generations["dashboard"],
        )

    assert output.joinpath("index.html").read_bytes() == expected


def test_forced_export_keeps_recovery_when_destination_is_reclaimed(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    directory_identity = output_module.directory_identity

    def reclaim_destination(
        filesystem: export_module.SecureDirectory,
        path: Path,
    ) -> tuple[tuple[object, ...], ...] | None:
        identity = directory_identity(filesystem, path)
        if path.name.startswith(".marimo-studio-export-recovery-"):
            output.mkdir()
            output.joinpath("concurrent.txt").write_text("keep", encoding="utf-8")
            return (
                (*identity, ("changed",)) if identity is not None else (("changed",),)
            )
        return identity

    monkeypatch.setattr(output_module, "directory_identity", reclaim_destination)

    with pytest.raises(StaticExportError, match="previous output is preserved"):
        export_view(notebook_path, output, force=True)

    assert output.joinpath("concurrent.txt").read_text(encoding="utf-8") == "keep"
    recoveries = tuple(tmp_path.glob(".marimo-studio-export-recovery-*"))
    assert len(recoveries) == 1
    assert recoveries[0].joinpath("index.html").is_file()


def test_forced_export_retries_an_occupied_recovery_name(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    first = tmp_path / f".marimo-studio-export-recovery-{'00' * 16}"
    second = tmp_path / f".marimo-studio-export-recovery-{'11' * 16}"
    first.mkdir()
    first.joinpath("sentinel.txt").write_text("keep", encoding="utf-8")
    names = iter((first.name, second.name))
    monkeypatch.setattr(
        secure_rename,
        "temporary_sibling_name",
        lambda kind: (
            next(names)
            if kind == "export-recovery"
            else pytest.fail(f"Unexpected temporary kind: {kind}")
        ),
    )

    export_view(notebook_path, output, force=True)

    assert first.joinpath("sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert output.joinpath("index.html").is_file()
    assert not second.exists()


def test_forced_export_restores_output_after_replacement_failures(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    expected = output.joinpath("index.html").read_bytes()
    directory_identity = output_module.directory_identity
    publish_absent = output_module.publish_absent

    def fail_recovery_read(
        filesystem: export_module.SecureDirectory,
        path: Path,
    ) -> tuple[tuple[object, ...], ...] | None:
        if path.name.startswith(".marimo-studio-export-recovery-"):
            raise PermissionError("recovery identity unavailable")
        return directory_identity(filesystem, path)

    def fail_bundle(
        filesystem: export_module.SecureDirectory,
        staged: Path,
        destination: Path,
    ) -> None:
        if staged.name == "bundle":
            raise PermissionError("bundle commit failed")
        publish_absent(filesystem, staged, destination)

    failures = (
        ("directory_identity", fail_recovery_read, "Could not verify previous"),
        ("publish_absent", fail_bundle, "Could not replace"),
    )
    for attribute, failure, message in failures:
        with monkeypatch.context() as patch:
            patch.setattr(output_module, attribute, failure)
            with pytest.raises(StaticExportError, match=message):
                export_view(notebook_path, output, force=True)

        assert output.joinpath("index.html").read_bytes() == expected, attribute


def test_export_detects_a_concurrently_substituted_empty_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "site"
    output.mkdir()
    staged = tmp_path / "staging" / "bundle"
    staged.mkdir(parents=True)
    staged.joinpath("index.html").write_text("new", encoding="utf-8")
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    original = tmp_path / "original"
    swapped = False

    with secure_directory(tmp_path) as filesystem:
        target = output_module.OutputTarget(
            output,
            output_module.directory_identity(filesystem, output),
            filesystem,
        )
        replace = filesystem.replace
        rename_to_temporary = filesystem.rename_to_temporary_sibling

        def swap_before_commit(
            source: Path,
            kind: output_module.TemporarySiblingKind,
        ) -> Path:
            nonlocal swapped
            if source == output and not swapped:
                swapped = True
                replace(output, original)
                replace(alternate, output)
            return rename_to_temporary(source, kind)

        monkeypatch.setattr(
            filesystem,
            "rename_to_temporary_sibling",
            swap_before_commit,
        )

        with pytest.raises(StaticExportError, match="Output changed"):
            output_module.commit_bundle(staged, target)

    assert swapped
    assert output.is_dir() and not tuple(output.iterdir())
    assert original.is_dir() and not tuple(original.iterdir())


def test_export_view_replaces_an_existing_bundle_only_with_force(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    output = _existing_export(notebook_path, tmp_path)
    output.joinpath("stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(StaticExportError, match="Pass --force"):
        export_view(notebook_path, output)

    export_view(notebook_path, output, force=True)
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

    with pytest.raises(StaticExportError, match="Pass --force"):
        export_view(notebook_path, output)


def test_export_reports_a_non_directory_output_parent(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configure_export_view(notebook_path)
    parent = tmp_path / "not-a-directory"
    parent.write_text("file", encoding="utf-8")

    with pytest.raises(StaticExportError, match="secure static export parent"):
        export_view(notebook_path, parent / "child" / "site")


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
                force=True,
            )
        except StaticExportError as error:
            assert "overlaps a static export source" in str(error), label
        else:
            pytest.fail(f"{label} accepted a destructive static export")

        assert output.exists() is existed, label

    assert notebook_path.is_file()
    assert (studio.views["executive"].root / "view.toml").is_file()
