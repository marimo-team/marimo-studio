from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import ViewProject
from marimo_studio.view_providers._builtin import _deno

from ..cli.commands_test_support import _run_cli
from ..helpers import empty_notebook_source, link_directory


@pytest.mark.supported_python
@pytest.mark.native_process
def test_inspection_requests_reuse_provider_cache_across_processes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "dashboard"
    project.mkdir()
    environment = {**os.environ, "MARIMO_STUDIO_CACHE_DIR": str(tmp_path / "cache")}
    script = """
import json
import sys
from pathlib import Path

from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers import ViewProject

root = Path(sys.argv[1])
project = ViewProject("dashboard", root, root / "view.toml", sys.argv[2], {})
cache = inspection_request(project).cache_root
cache.mkdir(parents=True, exist_ok=True)
marker = cache / "dependency"
previous = marker.read_text() if marker.exists() else None
marker.write_text("cached dependency")
print(json.dumps({"root": str(cache), "previous": previous}))
"""

    def request(provider: str) -> dict[str, str | None]:
        result = subprocess.run(
            [sys.executable, "-c", script, str(project), provider],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    project.chmod(0o555)
    try:
        first = request("marimo-studio/svelte")
        second = request("marimo-studio/svelte")
        other = request("marimo-studio/react")
    finally:
        project.chmod(0o755)

    assert first["root"] == second["root"]
    assert first["previous"] is None
    assert second["previous"] == "cached dependency"
    assert other["root"] != first["root"]
    assert other["previous"] is None
    assert list(project.iterdir()) == []


@pytest.mark.supported_python
@pytest.mark.skipif(os.name != "posix", reason="POSIX directory permissions")
def test_inspection_cache_is_private_to_the_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "marimo-studio"
    monkeypatch.setenv("MARIMO_STUDIO_CACHE_DIR", str(cache))
    project = ViewProject(
        "dashboard", tmp_path, tmp_path / "view.toml", "acme/html", {}
    )

    root = inspection_request(project).cache_root

    for directory in (cache, cache / "inspection", root):
        assert directory.stat().st_mode & 0o777 == 0o700


@pytest.mark.supported_python
@pytest.mark.skipif(os.name != "posix", reason="POSIX directory permissions")
@pytest.mark.parametrize("kind", ["public", "file"])
def test_inspection_rejects_unsafe_cache_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    cache = tmp_path / "marimo-studio"
    if kind == "public":
        cache.mkdir()
        cache.chmod(0o755)
    else:
        cache.write_text("occupied", encoding="utf-8")
    monkeypatch.setenv("MARIMO_STUDIO_CACHE_DIR", str(cache))
    project = ViewProject(
        "dashboard", tmp_path, tmp_path / "view.toml", "acme/html", {}
    )

    with pytest.raises(ConfigurationError):
        inspection_request(project)


@pytest.mark.supported_python
def test_inspection_rejects_linked_cache_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "marimo-studio"
    link_directory(tmp_path, cache)
    monkeypatch.setenv("MARIMO_STUDIO_CACHE_DIR", str(cache))
    project = ViewProject(
        "dashboard", tmp_path, tmp_path / "view.toml", "acme/html", {}
    )

    with pytest.raises(ConfigurationError, match="regular directory"):
        inspection_request(project)


def test_inspection_uses_a_process_cache_when_the_user_cache_is_unusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    monkeypatch.delenv("MARIMO_STUDIO_CACHE_DIR")
    monkeypatch.setattr(
        "marimo_studio._views.inspection_cache.user_cache_path",
        lambda *_args, **_kwargs: occupied / "marimo-studio",
    )
    project = ViewProject(
        "dashboard", tmp_path, tmp_path / "view.toml", "acme/html", {}
    )

    with caplog.at_level(logging.WARNING, logger="marimo.studio"):
        first = inspection_request(project).cache_root
        second = inspection_request(project).cache_root

    assert first == second
    assert occupied not in first.parents
    assert "MARIMO_STUDIO_CACHE_DIR" in caplog.text


def test_inspection_cache_location_must_be_absolute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARIMO_STUDIO_CACHE_DIR", "relative/cache")
    project = ViewProject(
        "dashboard", tmp_path, tmp_path / "view.toml", "acme/html", {}
    )

    with pytest.raises(ConfigurationError, match="must be an absolute path"):
        inspection_request(project)


@pytest.mark.deno
@pytest.mark.native_process
@pytest.mark.skipif(
    not _deno.deno_availability().available,
    reason="marimo-studio[deno] is unavailable",
)
@pytest.mark.parametrize("provider", ["svelte", "react", "notebook-kit"])
def test_unchanged_deno_build_reuses_dependencies_with_registry_unavailable(
    tmp_path: Path,
    runtime_assets: Path,
    provider: str,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(empty_notebook_source(), encoding="utf-8")
    environment: dict[str, str] = {}
    created = _run_cli(
        runtime_assets,
        "view",
        "create",
        "dashboard",
        "--target",
        str(notebook),
        "--starter",
        f"marimo-studio/{provider}:default",
        "--json",
        environment=environment,
    )
    assert created.returncode == 0, created.stderr
    arguments = ("view", "build", "dashboard", "--target", str(notebook), "--json")
    built = _run_cli(runtime_assets, *arguments, environment=environment)
    assert built.returncode == 0, built.stderr

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        environment[name] = environment[name.lower()] = "http://127.0.0.1:9"
    environment["NO_PROXY"] = environment["no_proxy"] = ""
    rebuilt = _run_cli(runtime_assets, *arguments, environment=environment)

    assert rebuilt.returncode == 0, rebuilt.stderr
    assert (
        json.loads(rebuilt.stdout)["revision"] == json.loads(built.stdout)["revision"]
    )
