"""Protect source document confinement, encoding, and size boundaries."""

import os
from pathlib import Path

import pytest

import marimo_studio._views.sources as sources_module
from marimo_studio._views.sources import read_source, write_source
from marimo_studio.errors import (
    ConfigurationError,
    SourceEncodingError,
    SourceNotFoundError,
    SourceTooLargeError,
    ViewGenerationConflictError,
)

from .source_test_support import SOURCE_PATH
from .source_test_support import document as _document
from .source_test_support import studio as _studio


def test_source_read_rejects_files_outside_the_view_contract(
    notebook_path: Path,
) -> None:
    studio = _studio(notebook_path)

    with pytest.raises(SourceNotFoundError):
        read_source(studio, "dashboard", "../analysis.py")


def test_source_write_rejects_a_view_file_replaced_by_a_symlink(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    studio = _studio(notebook_path)
    document = studio.views["dashboard"].root / SOURCE_PATH
    external = tmp_path / "external.html"
    external.write_text(_document("external"), encoding="utf-8")
    document.unlink()
    document.symlink_to(external)

    with pytest.raises(SourceNotFoundError, match="Unknown source document"):
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("blue"),
            "sha256:untrusted",
        )

    assert external.read_text(encoding="utf-8") == _document("external")


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_source_write_rejects_a_symlinked_view_mutation_lock(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    studio = _studio(notebook_path)
    current = read_source(studio, "dashboard", SOURCE_PATH)
    control = studio.view_root / ".locks"
    control.mkdir(exist_ok=True)
    lock = control / "dashboard.lock"
    lock.unlink(missing_ok=True)
    external = tmp_path / "external.lock"
    external.write_text("external", encoding="utf-8")
    lock.symlink_to(external)

    with pytest.raises(ConfigurationError, match="symlink"):
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("blue"),
            current.revision,
        )

    assert external.read_text(encoding="utf-8") == "external"


def test_source_read_reports_invalid_utf8(notebook_path: Path) -> None:
    studio = _studio(notebook_path)
    (studio.views["dashboard"].root / SOURCE_PATH).write_bytes(b"<html>\xff")

    with pytest.raises(SourceEncodingError, match="must be UTF-8 text"):
        read_source(studio, "dashboard", SOURCE_PATH)


@pytest.mark.skipif(
    os.name == "nt", reason="descriptor-relative open is a POSIX boundary"
)
def test_source_read_rejects_a_symlink_swapped_before_open(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    document = studio.views["dashboard"].root / SOURCE_PATH
    external = tmp_path / "secret.txt"
    external.write_text("SECRET", encoding="utf-8")
    open_file = sources_module.os.open
    swapped = False

    def replace_then_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(path).name == document.name and dir_fd is not None and not swapped:
            swapped = True
            document.unlink()
            document.symlink_to(external)
        return open_file(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(sources_module.os, "open", replace_then_open)

    with pytest.raises(SourceNotFoundError):
        read_source(studio, "dashboard", SOURCE_PATH)


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_source_read_rejects_a_swapped_view_root(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    project = studio.views["dashboard"]
    document_path = project.root / SOURCE_PATH
    original = document_path.read_text(encoding="utf-8")
    retired = project.root.with_name("dashboard-retired")
    external = tmp_path / "external-view"
    external.mkdir()
    (external / SOURCE_PATH).write_text("SECRET", encoding="utf-8")
    open_file = sources_module.os.open
    swapped = False

    def replace_root_then_open(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(path).name == document_path.name and dir_fd is not None and not swapped:
            swapped = True
            project.root.rename(retired)
            project.root.symlink_to(external, target_is_directory=True)
        return open_file(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(sources_module.os, "open", replace_root_then_open)

    with pytest.raises(ConfigurationError):
        read_source(studio, "dashboard", SOURCE_PATH)

    assert swapped
    assert (retired / SOURCE_PATH).read_text(encoding="utf-8") == original
    assert (external / SOURCE_PATH).read_text(encoding="utf-8") == "SECRET"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_manifest_read_rejects_a_root_swapped_after_validation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    root = studio.views["dashboard"].root
    retired = root.with_name("dashboard-retired")
    external = tmp_path / "external-view"
    external.mkdir()
    (external / "view.toml").write_text("SECRET", encoding="utf-8")
    is_dir = Path.is_dir
    swapped = False

    def validate_then_swap(path: Path) -> bool:
        nonlocal swapped
        result = is_dir(path)
        if path == root and result and not swapped:
            swapped = True
            root.rename(retired)
            root.symlink_to(external, target_is_directory=True)
        return result

    monkeypatch.setattr(Path, "is_dir", validate_then_swap)

    with pytest.raises(
        (ConfigurationError, SourceNotFoundError, ViewGenerationConflictError)
    ):
        sources_module.read_view_manifest(studio, "dashboard")

    assert swapped
    assert (external / "view.toml").read_text(encoding="utf-8") == "SECRET"


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_source_write_keeps_its_commit_inside_a_swapped_view_root(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    project = studio.views["dashboard"]
    current = read_source(studio, "dashboard", SOURCE_PATH)
    retired = project.root.with_name("dashboard-retired")
    external = tmp_path / "external-view"
    external.mkdir()
    (external / SOURCE_PATH).write_text("SECRET", encoding="utf-8")
    open_file = sources_module.os.open
    swapped = False

    def replace_root_before_temporary(
        path: os.PathLike[str] | str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if (
            str(path).startswith(".marimo-studio-cas-")
            and dir_fd is not None
            and not swapped
        ):
            swapped = True
            project.root.rename(retired)
            project.root.symlink_to(external, target_is_directory=True)
        return open_file(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(sources_module.os, "open", replace_root_before_temporary)

    with pytest.raises(ConfigurationError):
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("blue"),
            current.revision,
        )

    assert (retired / SOURCE_PATH).read_text(encoding="utf-8") == _document("blue")
    assert (external / SOURCE_PATH).read_text(encoding="utf-8") == "SECRET"


def test_source_documents_enforce_the_file_size_boundary(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _studio(notebook_path)
    document = studio.view("dashboard").root / SOURCE_PATH
    short = _document("short")
    limit = len(short.encode("utf-8"))
    monkeypatch.setattr(sources_module, "SOURCE_DOCUMENT_MAX_BYTES", limit)
    document.write_text(_document("too-large"), encoding="utf-8")

    with pytest.raises(SourceTooLargeError):
        read_source(studio, "dashboard", SOURCE_PATH)

    document.write_text(short, encoding="utf-8")
    current = read_source(studio, "dashboard", SOURCE_PATH)
    with pytest.raises(SourceTooLargeError):
        write_source(
            studio,
            "dashboard",
            SOURCE_PATH,
            _document("too-large"),
            current.revision,
        )
