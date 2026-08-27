from __future__ import annotations

import re
from pathlib import Path

import marimo

from marimo_studio._validation.evidence import (
    RuntimeStatusReport,
    RuntimeStatusSnapshot,
    RuntimeStatusTransition,
)


def ready_runtime_status(
    view: str,
    revision: str,
    session_id: str | None = "s_123456",
    *,
    runtime: str = "server",
) -> RuntimeStatusReport:
    return RuntimeStatusReport(
        runtime=runtime,
        view=view,
        revision=revision,
        session_id=session_id,
        current=RuntimeStatusSnapshot(phase="ready"),
        transitions=(
            RuntimeStatusTransition(
                sequence=0,
                observed_at=1_000,
                phase="connecting",
            ),
            RuntimeStatusTransition(
                sequence=1,
                observed_at=1_100,
                phase="ready",
                revision=revision,
                session_id=session_id,
            ),
        ),
    )


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
