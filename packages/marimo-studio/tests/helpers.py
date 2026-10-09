from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

import marimo
import pytest


def link_directory(target: Path, link: Path) -> None:
    """Point ``link`` at ``target`` as a symlink, or as a junction on Windows.

    Creating a junction needs no Windows privilege, unlike a symlink.
    """
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return
    link.symlink_to(target, target_is_directory=True)


def replace_app_shell(document: str, content: str) -> str:
    """Replace the authored contents of the single application shell."""
    opening = re.search(
        r'<main\b[^>]*\bid=["\']app-shell["\'][^>]*>',
        document,
    )
    if opening is None:
        raise AssertionError("Document has no #app-shell main element")
    closing = document.find("</main>", opening.end())
    if closing < 0:
        raise AssertionError("Document has no closing #app-shell tag")
    return (
        document[: opening.start()]
        + f'<main id="app-shell">{content}</main>'
        + document[closing + len("</main>") :]
    )


def empty_notebook_source() -> str:
    return (
        "import marimo\n"
        "\n"
        f'__generated_with = "{marimo.__version__}"\n'
        "app = marimo.App()\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n"
    )


def no_display_notebook_source() -> str:
    return (
        "import marimo\n"
        "\n"
        f'__generated_with = "{marimo.__version__}"\n'
        'app = marimo.App(app_title="No display results")\n'
        "\n"
        "\n"
        "@app.cell\n"
        "def producer():\n"
        "    value = 1\n"
        "    return (value,)\n"
        "\n"
        "\n"
        "@app.cell\n"
        "def consumer(value):\n"
        "    hidden = value * 2\n"
        "    hidden;\n"
        "    return (hidden,)\n"
        "\n"
        "\n"
        "@app.cell(disabled=True)\n"
        "def disabled_output():\n"
        '    "Disabled output"\n'
        "    return\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n"
    )


def notebook_source(marker: Path, *, dependencies: tuple[str, ...] = ()) -> str:
    metadata = ""
    if dependencies:
        values = ", ".join(f'"{dependency}"' for dependency in dependencies)
        metadata = (
            "# /// script\n"
            '# requires-python = ">=3.10"\n'
            f"# dependencies = [{values}]\n"
            "# ///\n"
        )
    return (
        f"{metadata}"
        "import marimo\n"
        "\n"
        f'__generated_with = "{marimo.__version__}"\n'
        "app = marimo.App()\n"
        "\n"
        "\n"
        "@app.cell\n"
        "def _():\n"
        "    from pathlib import Path\n"
        f'    marker = Path(r"{marker}")\n'
        '    marker.write_text("executed", encoding="utf-8")\n'
        "    x = 2\n"
        "    return (x,)\n"
        "\n"
        "\n"
        "@app.cell\n"
        "def _(x):\n"
        "    doubled = x * 2\n"
        "    doubled\n"
        "    return (doubled,)\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n"
    )


def update_notebook_config(
    path: Path,
    update: Callable[[MutableMapping[str, Any]], None],
) -> None:
    """Rewrite the notebook-local marimo-studio table with an atomic save."""
    from marimo_studio._workspace.metadata import updated_notebook_config_source

    source = path.read_text(encoding="utf-8")
    temporary = path.with_name(f".{path.name}.edit")
    temporary.write_text(
        updated_notebook_config_source(path, source, update), encoding="utf-8"
    )
    os.replace(temporary, path)


def write_marimohub_context(
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    **fields: object,
) -> Path:
    """Publish a marimohub session context and point the process at it."""
    path = directory / "marimohub-context.json"
    context = {
        "schema_version": 1,
        "public_url": "https://hub.example/proxy/token/",
        "notebook_url": "https://hub.example/projects/p/notebooks/n",
        "exposure_mode": "proxy",
        "persistence_mode": "workspace",
        "session_mode": "edit",
        **fields,
    }
    path.write_text(json.dumps(context), encoding="utf-8")
    monkeypatch.setenv("MARIMOHUB_CONTEXT_FILE", str(path))
    return path
