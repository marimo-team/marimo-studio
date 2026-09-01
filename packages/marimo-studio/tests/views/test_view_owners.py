from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

import marimo_studio._workspace.config as workspace_config
import marimo_studio._workspace.generation as workspace_generation
import marimo_studio._workspace.view_owners as owner_module
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.view_owners import (
    decode_view_owner,
    encode_view_owner,
    load_view_owner,
    view_owner_path,
)
from marimo_studio.errors import ConfigurationError, WorkspaceGenerationConflictError


def test_external_copy_gets_a_fresh_per_name_owner(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    monkeypatch.setattr(
        workspace_generation,
        "directory_generation",
        lambda _path: "forced-shared-directory-owner",
    )
    original = load_studio(notebook_path)
    shutil.copytree(
        original.views["dashboard"].root,
        original.view_root / "report",
    )

    adopted = load_studio(notebook_path)

    assert set(adopted.views) == {"dashboard", "report"}
    assert adopted.view_generations["report"] != (adopted.view_generations["dashboard"])
    assert load_view_owner(adopted.view_root, "report").present is True


def test_external_rename_tombstones_the_old_name_and_adopts_the_new_name(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    observed = load_studio(notebook_path)
    old_generation = observed.view_generations["executive"]
    observed.views["executive"].root.rename(observed.view_root / "report")

    renamed = load_studio(notebook_path)

    assert set(renamed.views) == {"dashboard", "report"}
    assert load_view_owner(renamed.view_root, "executive").present is False
    assert load_view_owner(renamed.view_root, "report").present is True
    assert renamed.view_generations["report"] != old_generation


def test_observed_external_absence_rotates_an_exact_same_name_recreation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    monkeypatch.setattr(
        workspace_generation,
        "directory_generation",
        lambda _path: "forced-reused-directory-owner",
    )
    observed = load_studio(notebook_path)
    target = observed.views["executive"].root
    replacement = tmp_path / "replacement"
    shutil.copytree(target, replacement)
    shutil.rmtree(target)

    absent = load_studio(notebook_path)
    assert "executive" not in absent.views
    assert load_view_owner(absent.view_root, "executive").present is False

    shutil.copytree(replacement, target)
    recreated = load_studio(notebook_path)

    assert (
        recreated.view_generations["executive"]
        != (observed.view_generations["executive"])
    )


def test_unobserved_recreation_with_the_same_directory_owner_keeps_generation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    monkeypatch.setattr(
        workspace_generation,
        "directory_generation",
        lambda _path: "forced-reused-directory-owner",
    )
    observed = load_studio(notebook_path)
    target = observed.views["dashboard"].root
    replacement = tmp_path / "changed-replacement"
    shutil.copytree(target, replacement)
    replacement.joinpath("index.html").write_text(
        "<!doctype html><title>changed replacement</title>",
        encoding="utf-8",
    )
    shutil.rmtree(target)
    shutil.copytree(replacement, target)

    recreated = load_studio(notebook_path)

    assert (
        recreated.view_generations["dashboard"]
        == (observed.view_generations["dashboard"])
    )


def test_concurrent_external_adoption_has_one_durable_owner(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    shutil.copytree(studio.views["dashboard"].root, studio.view_root / "report")
    ready = Barrier(2)

    def load() -> str:
        ready.wait(timeout=2)
        return load_studio(notebook_path).view_generations["report"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: load(), range(2)))

    current = load_studio(notebook_path)
    assert set(results) == {current.view_generations["report"]}


def test_reconciliation_refreshes_membership_after_concurrent_creation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    discover = workspace_config.discover_views
    generation = "a" * 64
    raced = False

    def create_after_discovery(view_root: Path):
        nonlocal raced
        discovered = discover(view_root)
        if not raced:
            raced = True
            shutil.copytree(
                discovered["dashboard"].root,
                view_root / "report",
            )
            view_owner_path(view_root, "report").write_text(
                encode_view_owner(present=True, generation=generation),
                encoding="utf-8",
            )
        return discovered

    monkeypatch.setattr(workspace_config, "discover_views", create_after_discovery)

    current = load_studio(notebook_path)

    assert set(current.views) == {"dashboard", "report"}
    assert load_view_owner(studio.view_root, "report").generation == generation


def test_reconciliation_refreshes_membership_after_concurrent_deletion(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "report")
    studio = load_studio(notebook_path)
    discover = workspace_config.discover_views
    generation = "b" * 64
    raced = False

    def delete_after_discovery(view_root: Path):
        nonlocal raced
        discovered = discover(view_root)
        if not raced:
            raced = True
            shutil.rmtree(discovered["report"].root)
            view_owner_path(view_root, "report").write_text(
                encode_view_owner(present=False, generation=generation),
                encoding="utf-8",
            )
        return discovered

    monkeypatch.setattr(workspace_config, "discover_views", delete_after_discovery)

    current = load_studio(notebook_path)

    assert set(current.views) == {"dashboard"}
    owner = load_view_owner(studio.view_root, "report")
    assert owner.present is False
    assert owner.generation == generation


def test_materialization_rejects_a_mixed_same_name_replacement(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    discover = workspace_config.discover_views
    raced = False

    def replace_after_discovery(view_root: Path):
        nonlocal raced
        discovered = discover(view_root)
        if not raced:
            raced = True
            discovered["dashboard"].manifest.write_text(
                'schema = 1\nprovider = "marimo-studio/svelte"\n',
                encoding="utf-8",
            )
            view_owner_path(view_root, "dashboard").write_text(
                encode_view_owner(present=True),
                encoding="utf-8",
            )
        return discovered

    monkeypatch.setattr(workspace_config, "discover_views", replace_after_discovery)

    with pytest.raises(WorkspaceGenerationConflictError):
        load_studio(notebook_path)

    monkeypatch.setattr(workspace_config, "discover_views", discover)
    current = load_studio(notebook_path)
    assert current.views["dashboard"].provider == "marimo-studio/svelte"
    assert (
        current.view_generations["dashboard"] != (studio.view_generations["dashboard"])
    )


@pytest.mark.parametrize(
    "source",
    (
        'schema = 1\ngeneration = "short"\npresent = true\n',
        'schema = 1\ngeneration = "' + "0" * 64 + '"\npresent = "yes"\n',
        'schema = 2\ngeneration = "' + "0" * 64 + '"\npresent = true\n',
    ),
)
def test_view_owner_rejects_invalid_records(tmp_path: Path, source: str) -> None:
    with pytest.raises(ConfigurationError):
        decode_view_owner(source, tmp_path / "dashboard.toml")


@pytest.mark.parametrize(
    "name",
    (
        "api.toml",
        f"{'a' * 241}.toml",
        "notes.txt",
    ),
)
def test_owner_catalog_rejects_unowned_record_names(
    notebook_path: Path,
    name: str,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    studio.view_root.joinpath(".owners", name).write_text(
        encode_view_owner(present=True),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError):
        load_studio(notebook_path)


def test_provider_free_catalog_does_not_adopt_an_overlength_view_name(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    name = "a" * 241
    invalid = studio.view_root / name
    invalid.mkdir()
    invalid.joinpath("view.toml").write_text(
        'schema = 1\nprovider = "marimo-studio/vanilla"\n',
        encoding="utf-8",
    )

    workspace_generation.provider_free_catalog_generation(
        load_studio_definition(notebook_path)
    )

    assert not view_owner_path(studio.view_root, name).exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="symlink creation needs elevated Windows access",
)
@pytest.mark.parametrize("target", ("directory", "record"))
def test_owner_catalog_rejects_symlinked_state(
    notebook_path: Path,
    tmp_path: Path,
    target: str,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    owners = studio.view_root / ".owners"
    if target == "directory":
        retired = owners.with_name("retired-owners")
        owners.rename(retired)
        owners.symlink_to(retired, target_is_directory=True)
    else:
        owner = view_owner_path(studio.view_root, "dashboard")
        external = tmp_path / "external-owner.toml"
        external.write_bytes(owner.read_bytes())
        owner.unlink()
        owner.symlink_to(external)

    with pytest.raises(ConfigurationError):
        load_studio(notebook_path)


def test_multi_owner_reconciliation_rolls_back_together(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    executive_owner = view_owner_path(studio.view_root, "executive")
    original_executive_owner = executive_owner.read_bytes()
    shutil.rmtree(studio.views["executive"].root)
    shutil.copytree(studio.views["dashboard"].root, studio.view_root / "report")
    transaction = owner_module.write_file_transaction

    @contextmanager
    def fail_after_writes(*args: Any, **kwargs: Any) -> Iterator[None]:
        with transaction(*args, **kwargs):
            raise RuntimeError("forced owner reconciliation failure")
        yield

    monkeypatch.setattr(owner_module, "write_file_transaction", fail_after_writes)

    with pytest.raises(RuntimeError, match="forced owner reconciliation"):
        load_studio(notebook_path)

    assert executive_owner.read_bytes() == original_executive_owner
    assert not view_owner_path(studio.view_root, "report").exists()


def test_owner_record_is_outside_the_provider_project(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)

    owner = view_owner_path(studio.view_root, "dashboard")
    assert owner.parent == studio.view_root / ".owners"
    assert studio.views["dashboard"].root not in owner.parents


def test_view_creation_reports_the_durable_owner_write(notebook_path: Path) -> None:
    planned = prepare_view(notebook_path, dry_run=True)
    owner = view_owner_path(planned.root.parent, "dashboard")

    assert owner in planned.created
    assert not owner.exists()

    created = prepare_view(notebook_path)
    assert owner in created.created
    assert owner.is_file()


def test_provider_free_catalog_does_not_adopt_an_invalid_sibling_name(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    studio.views["dashboard"].manifest.write_text("schema = [\n", encoding="utf-8")
    invalid = studio.view_root / "Bad"
    invalid.mkdir()
    invalid.joinpath("view.toml").write_text(
        'schema = 1\nprovider = "marimo-studio/vanilla"\n',
        encoding="utf-8",
    )
    definition = load_studio_definition(notebook_path)

    workspace_generation.provider_free_catalog_generation(definition)

    assert not view_owner_path(studio.view_root, "Bad").exists()
    shutil.rmtree(invalid)
    workspace_generation.provider_free_catalog_generation(definition)
