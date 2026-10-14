"""Resolve the source that installs the Studio running this process."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest

from marimo_studio._workspace import installation
from marimo_studio._workspace.installation import invoking_studio


def _installed(monkeypatch: pytest.MonkeyPatch, direct_url: object | None) -> None:
    recorded = (
        None
        if direct_url is None
        else (direct_url if isinstance(direct_url, str) else json.dumps(direct_url))
    )
    studio = SimpleNamespace(
        version="0.1.6",
        read_text=lambda name: recorded if name == "direct_url.json" else None,
    )

    def installed(name: str) -> SimpleNamespace:
        if name == "marimo-studio":
            return studio
        raise PackageNotFoundError(name)

    monkeypatch.setattr(installation, "distribution", installed)


def test_editable_checkout_installs_its_source_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _installed(monkeypatch, {"url": tmp_path.as_uri(), "dir_info": {"editable": True}})

    studio = invoking_studio()

    assert studio is not None
    assert studio.editable == tmp_path
    assert studio.requirement == f"-e {tmp_path}"


def test_local_wheel_installs_the_recorded_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "marimo_studio-0.1.6-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    _installed(monkeypatch, {"url": wheel.as_uri(), "archive_info": {}})

    studio = invoking_studio()

    assert studio is not None
    assert studio.requirement == f"marimo-studio @ {wheel.as_uri()}"


@pytest.mark.parametrize(
    ("direct_url", "requirement"),
    (
        (
            {
                "url": "https://example.test/marimo_studio-0.1.6-py3-none-any.whl",
                "archive_info": {},
            },
            "marimo-studio @ https://example.test/marimo_studio-0.1.6-py3-none-any.whl",
        ),
        (
            {
                "url": "https://github.com/marimo-team/marimo-studio",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
            },
            "marimo-studio @ git+https://github.com/marimo-team/marimo-studio@abc123",
        ),
        (
            {
                "url": "https://github.com/marimo-team/marimo-studio.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
                "subdirectory": "packages/marimo-studio",
            },
            "marimo-studio @ git+https://github.com/marimo-team/marimo-studio.git"
            "@abc123#subdirectory=packages/marimo-studio",
        ),
        (None, "marimo-studio==0.1.6"),
        (
            {"url": "file:///missing/marimo_studio.whl", "archive_info": {}},
            "marimo-studio==0.1.6",
        ),
        ("{not json", "marimo-studio==0.1.6"),
        ({"dir_info": {}}, "marimo-studio==0.1.6"),
    ),
    ids=(
        "remote-archive",
        "vcs-commit",
        "vcs-subdirectory",
        "index",
        "missing-local-file",
        "malformed",
        "no-url",
    ),
)
def test_other_sources_render_a_requirement(
    monkeypatch: pytest.MonkeyPatch,
    direct_url: object | None,
    requirement: str,
) -> None:
    _installed(monkeypatch, direct_url)

    studio = invoking_studio()

    assert studio is not None
    assert studio.requirement == requirement


def test_uninstalled_studio_has_no_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> SimpleNamespace:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(installation, "distribution", missing)

    assert invoking_studio() is None


@pytest.mark.parametrize("available", ("directory", "missing", "file"))
def test_editable_subdirectory_must_be_an_existing_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    available: str,
) -> None:
    source = tmp_path / "packages" / "marimo-studio"
    if available == "directory":
        source.mkdir(parents=True)
    elif available == "file":
        source.parent.mkdir()
        source.write_text("file", encoding="utf-8")
    _installed(
        monkeypatch,
        {
            "url": tmp_path.as_uri(),
            "dir_info": {"editable": True},
            "subdirectory": "packages/marimo-studio",
        },
    )

    studio = invoking_studio()

    assert studio is not None
    assert studio.requirement == (
        f"-e {source}" if available == "directory" else "marimo-studio==0.1.6"
    )
