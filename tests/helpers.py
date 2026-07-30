from __future__ import annotations

from pathlib import Path

import marimo


def notebook_source(marker: Path, *, dependencies: tuple[str, ...] = ()) -> str:
    metadata = ""
    if dependencies:
        values = ", ".join(f'"{dependency}"' for dependency in dependencies)
        metadata = (
            "# /// script\n"
            '# requires-python = ">=3.11"\n'
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
