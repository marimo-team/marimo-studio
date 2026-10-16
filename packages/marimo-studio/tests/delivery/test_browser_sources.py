from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import marimo_studio._delivery.assets as assets_module
from marimo_studio.errors import ProtocolError

OUTPUT = "packages/marimo-studio/src/marimo_studio/_static/browser"
SOURCES = {
    "packages/protocol/src/projections.ts": b"export const site = 1;\n",
    "packages/studio/src/main.tsx": b"render();\n",
}


def write_checkout(
    root: Path,
    *,
    output: str = OUTPUT,
    record: dict[str, object] | None = None,
) -> Path:
    """Write sources and the record a browser build leaves beside its assets."""
    (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
    for path, content in SOURCES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)
    browser = root / output
    browser.mkdir(parents=True)
    (browser.parent / "build-sources.json").write_text(
        json.dumps(
            record
            or {
                "schema": 1,
                "output": OUTPUT,
                "files": {
                    path: hashlib.sha256(content).hexdigest()
                    for path, content in SOURCES.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return browser


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(assets_module, "runtime_assets_path", lambda: tmp_path / OUTPUT)
    return tmp_path


def test_checkout_serves_assets_built_from_its_sources(checkout: Path) -> None:
    write_checkout(checkout)

    assets_module.validate_runtime_sources()


def test_checkout_rejects_assets_built_from_other_sources(checkout: Path) -> None:
    write_checkout(checkout)
    (checkout / "packages/protocol/src/projections.ts").write_text(
        "export const site = 2;\n", encoding="utf-8"
    )
    (checkout / "packages/studio/src/main.tsx").unlink()

    with pytest.raises(ProtocolError) as error:
        assets_module.validate_runtime_sources()

    message = str(error.value)
    assert error.value.code == "protocol-error"
    assert "packages/protocol/src/projections.ts and 1 other file" in message
    assert f"Run `make build` in {checkout.resolve()}" in message


def test_crlf_checkout_matches_the_digest_of_its_lf_content(checkout: Path) -> None:
    # The browser build test pins the same digest for "a\nb\n".
    write_checkout(
        checkout,
        record={
            "schema": 1,
            "output": OUTPUT,
            "files": {
                "packages/studio/src/main.tsx": (
                    "911169ddaaf146aff539f58c26c489af3b892dff0fe283c1c264c65ae5aa59a2"
                )
            },
        },
    )
    (checkout / "packages/studio/src/main.tsx").write_bytes(b"a\r\nb\r\n")

    assets_module.validate_runtime_sources()


@pytest.mark.parametrize(
    "record",
    [
        {"schema": True, "output": OUTPUT, "files": {}},
        {"schema": 1, "output": OUTPUT, "files": {"../outside.ts": "0" * 64}},
        {"schema": 1, "output": OUTPUT, "files": {"/etc/hosts": "0" * 64}},
        {"schema": 1, "output": OUTPUT, "files": {"src/main.tsx": "not-a-digest"}},
        {"schema": 1, "output": "../browser", "files": {}},
    ],
)
def test_checkout_rejects_an_invalid_source_record(
    checkout: Path, record: dict[str, object]
) -> None:
    write_checkout(checkout, record=record)

    with pytest.raises(ProtocolError) as error:
        assets_module.validate_runtime_sources()

    assert str((checkout / OUTPUT).parent / "build-sources.json") in str(error.value)
    assert "make build" in str(error.value)


def test_assets_without_a_source_record_are_served(checkout: Path) -> None:
    browser = write_checkout(checkout)
    (browser.parent / "build-sources.json").unlink()
    (checkout / "packages/protocol/src/projections.ts").unlink()

    assets_module.validate_runtime_sources()


def test_assets_installed_outside_their_checkout_are_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = "lib/python3.12/site-packages/marimo_studio/_static/browser"
    write_checkout(tmp_path, output=installed)
    monkeypatch.setattr(
        assets_module, "runtime_assets_path", lambda: tmp_path / installed
    )
    (tmp_path / "packages/protocol/src/projections.ts").unlink()

    assets_module.validate_runtime_sources()


def test_package_copied_outside_a_workspace_is_served(checkout: Path) -> None:
    write_checkout(checkout)
    (checkout / "pnpm-workspace.yaml").unlink()
    (checkout / "packages/protocol/src/projections.ts").unlink()

    assets_module.validate_runtime_sources()


def _import_in_child(assets: Path, statement: str) -> subprocess.CompletedProcess[str]:
    # The child process sees the checkout's real assets unless it is pointed at
    # the stale fixture before Studio's entry points load.
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path

        import marimo_studio._delivery.assets as assets

        assets.runtime_assets_path = lambda: Path(sys.argv[1])
        {statement}
        """
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "MARIMO_EXPORT_OWNED_SESSION"
    }
    return subprocess.run(
        [sys.executable, "-c", script, str(assets)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )


def test_marimo_server_startup_reports_stale_assets(checkout: Path) -> None:
    browser = write_checkout(checkout)
    (checkout / "packages/protocol/src/projections.ts").write_text(
        "export const site = 2;\n", encoding="utf-8"
    )

    completed = _import_in_child(browser, "import marimo_studio._entrypoints")

    error = completed.stderr.strip().splitlines()[-1]
    assert completed.returncode != 0
    assert error.startswith("click.exceptions.ClickException: ")
    assert "packages/protocol/src/projections.ts" in error
    assert f"Run `make build` in {checkout.resolve()}" in error


def test_kernel_lifespan_loads_beside_stale_assets(checkout: Path) -> None:
    browser = write_checkout(checkout)
    (checkout / "packages/protocol/src/projections.ts").write_text(
        "export const site = 2;\n", encoding="utf-8"
    )
    (kernel,) = (
        point
        for point in entry_points(group="marimo.kernel.lifespan")
        if point.name == "marimo-studio"
    )

    completed = _import_in_child(
        browser,
        "from importlib import import_module; "
        f"assert callable(getattr(import_module({kernel.module!r}), "
        f"{kernel.attr!r}))",
    )

    assert completed.returncode == 0, completed.stderr
