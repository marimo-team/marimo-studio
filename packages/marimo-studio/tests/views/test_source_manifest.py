"""Protect source access to the durable view manifest contract."""

from pathlib import Path

import pytest

import marimo_studio._filesystem.secure as secure_files
import marimo_studio._views.sources as sources_module
from marimo_studio._views.sources import read_source, write_source
from marimo_studio._workspace import load_studio
from marimo_studio.errors import SourceConflictError, SourceValidationError
from marimo_studio.view_providers._host import provider_registry

from .source_test_support import studio as _studio


def test_manifest_write_uses_studio_owned_validation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", "view.toml")

    def fail_registry() -> object:
        pytest.fail("manifest write loaded the provider registry")

    monkeypatch.setattr(sources_module, "provider_registry", fail_registry)
    content = current.content + '\n[options]\nentrypoint = "index.html"\n'

    updated = write_source(
        studio,
        "dashboard",
        "view.toml",
        content,
        current.revision,
    )

    assert updated.content == content


def test_manifest_write_rejects_invalid_candidates_without_replacing_source(
    notebook_path: Path,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", "view.toml")

    with pytest.raises(SourceValidationError):
        write_source(
            studio,
            "dashboard",
            "view.toml",
            "schema = ",
            current.revision,
        )

    assert read_source(studio, "dashboard", "view.toml") == current


def test_manifest_source_does_not_depend_on_provider_inspection(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    provider = provider_registry().get(studio.views["dashboard"].provider)

    def unavailable_inspection(*_args: object) -> None:
        raise RuntimeError("provider inspection is unavailable")

    monkeypatch.setattr(provider, "inspect", unavailable_inspection)
    current = read_source(studio, "dashboard", "view.toml")

    assert current.content.startswith("schema = 1\n")


def test_manifest_write_keeps_provider_identity_and_accepts_provider_options(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    project = studio.view("dashboard")
    alternate = project.root / "alternate.html"
    alternate.write_text(
        (project.root / "index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    current = read_source(studio, "dashboard", "view.toml")
    provider = provider_registry().get(project.provider)
    monkeypatch.setattr(
        provider,
        "inspect",
        lambda _request: pytest.fail("manifest commit must not inspect the provider"),
    )
    options = (
        'schema = 1\nprovider = "marimo-studio/vanilla"\n\n'
        '[options]\nentrypoint = "alternate.html"\n'
    )

    updated = write_source(
        studio,
        "dashboard",
        "view.toml",
        options,
        current.revision,
    )

    assert updated.content == options
    with pytest.raises(SourceValidationError, match="keeps one provider"):
        write_source(
            load_studio(notebook_path),
            "dashboard",
            "view.toml",
            'schema = 1\nprovider = "marimo-studio/react"\n',
            updated.revision,
        )


def test_manifest_repair_retains_a_recoverable_provider_identity(
    notebook_path: Path,
) -> None:
    studio = _studio(notebook_path)
    manifest = studio.views["dashboard"].manifest
    manifest.write_text(
        'schema = 2\nprovider = "marimo-studio/vanilla"\n',
        encoding="utf-8",
    )
    current = read_source(studio, "dashboard", "view.toml")

    with pytest.raises(SourceValidationError, match="keeps one provider"):
        write_source(
            studio,
            "dashboard",
            "view.toml",
            'schema = 1\nprovider = "marimo-studio/react"\n',
            current.revision,
        )

    assert manifest.read_bytes() == current.content.encode("utf-8")


def test_manifest_write_commits_before_provider_diagnostics(
    notebook_path: Path,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", "view.toml")
    content = (
        'schema = 1\nprovider = "marimo-studio/vanilla"\n\n[options]\nunknown = true\n'
    )

    updated = write_source(
        studio,
        "dashboard",
        "view.toml",
        content,
        current.revision,
    )
    project = load_studio(notebook_path).view("dashboard")
    provider_diagnostics = sources_module.inspect_view_project_sync(project).diagnostics

    assert updated.content == content
    assert "provider-options-invalid" in {
        diagnostic.code for diagnostic in provider_diagnostics
    }


def test_manifest_commit_preserves_an_external_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", "view.toml")
    manifest = studio.views["dashboard"].manifest
    external = current.content + "# external edit\n"
    replace = secure_files.SecureDirectory.replace_file_if_identity
    edited = False

    def edit_then_replace(
        files: secure_files.SecureDirectory,
        path: Path,
        content: bytes,
        expected: secure_files.FileIdentity,
    ) -> None:
        nonlocal edited
        if path == manifest and not edited:
            edited = True
            manifest.write_text(external, encoding="utf-8")
        replace(files, path, content, expected)

    monkeypatch.setattr(
        secure_files.SecureDirectory,
        "replace_file_if_identity",
        edit_then_replace,
    )

    with pytest.raises(SourceConflictError):
        write_source(
            studio,
            "dashboard",
            "view.toml",
            current.content + "# browser edit\n",
            current.revision,
        )

    assert edited
    assert manifest.read_text(encoding="utf-8") == external
