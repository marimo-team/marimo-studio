from pathlib import Path

import pytest

from marimo_studio._workspace import load_studio
from marimo_studio._workspace.sources import read_source, write_source
from marimo_studio.errors import (
    ConfigurationError,
    SourceEncodingError,
    SourceNotFoundError,
)
from marimo_studio.workspace import ensure_view


def test_source_read_rejects_files_outside_the_view_contract(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)

    with pytest.raises(SourceNotFoundError):
        read_source(studio, "dashboard", "../analysis.py")


def test_optional_theme_opens_empty_and_is_created_on_first_edit(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    theme = studio.views["dashboard"].root / "theme.css"
    theme.unlink()

    loaded = read_source(studio, "dashboard", "theme.css")
    content = ":root { --primary: teal; }"
    saved = write_source(
        studio,
        "dashboard",
        "theme.css",
        content,
        loaded.revision,
    )

    assert loaded.content == ""
    assert saved.content == theme.read_text(encoding="utf-8") == content


def test_source_write_rejects_a_view_file_replaced_by_a_symlink(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    stylesheet = studio.views["dashboard"].root / "app.css"
    external = tmp_path / "external.css"
    external.write_text("body { color: red; }", encoding="utf-8")
    stylesheet.unlink()
    stylesheet.symlink_to(external)

    with pytest.raises(ConfigurationError, match="symlink"):
        write_source(
            studio,
            "dashboard",
            "app.css",
            "body { color: blue; }",
            "sha256:untrusted",
        )

    assert external.read_text(encoding="utf-8") == "body { color: red; }"


def test_source_read_reports_invalid_utf8(notebook_path: Path) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.views["dashboard"].root / "app.css").write_bytes(b"body {\xff}")

    with pytest.raises(SourceEncodingError, match="must be UTF-8 text"):
        read_source(studio, "dashboard", "app.css")
