"""Protect one Lens per Studio notebook alongside Marimo's automatic Lens."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import marimo
import pytest

from marimo_studio._compat.kernel_values.lens import LensMountPolicy
from marimo_studio._compat.runtime_probe import probe_runtime_in_worker

pytest.importorskip("marimo_lens")

_STUDIO_METADATA = """\
# /// script
# [tool.marimo-studio]
# default = "dashboard"
# ///
"""

_AUTHORED_LENS = {
    "documented": (
        "    studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)\n"
        "    None\n"
        "    return (studio_lens,)\n"
    ),
    "displayed": (
        "    studio_lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)\n"
        "    studio_lens\n"
        "    return (studio_lens,)\n"
    ),
    "anonymous": "    mo.output.append(Lens())\n    return\n",
}


def _notebook(path: Path, *, studio: bool, lens: str | None) -> Path:
    authored = ""
    if lens is not None:
        authored = (
            "@app.cell\n"
            "def _():\n"
            "    from marimo_lens import Lens\n"
            "    from marimo_studio import STUDIO_RESULT_SELECTOR\n"
            "    return Lens, STUDIO_RESULT_SELECTOR\n"
            "\n"
            "\n"
            "@app.cell\n"
            "def _(Lens, STUDIO_RESULT_SELECTOR, mo):\n"
            f"{_AUTHORED_LENS[lens]}"
            "\n"
            "\n"
        )
    path.write_text(
        (_STUDIO_METADATA if studio else "") + "import marimo\n"
        "\n"
        f'__generated_with = "{marimo.__version__}"\n'
        "app = marimo.App()\n"
        "\n"
        "\n"
        "@app.cell\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n"
        "\n"
        "\n"
        f"{authored}"
        # Counts the Lens instances this kernel holds after the other cells ran.
        "@app.cell\n"
        f"def _({'Lens, mo' if lens is not None else 'mo'}):\n"
        "    from marimo_lens import Lens as _Lens\n"
        "    from marimo._plugins.ui._impl.from_anywidget import anywidget\n"
        "    from marimo._runtime.context import get_context\n"
        "    from marimo._utils.flatten import contains_instance\n"
        "    _context = get_context()\n"
        "    _held = {}\n"
        "    def _collect(value):\n"
        "        if isinstance(value, _Lens):\n"
        "            _held[id(value)] = value\n"
        "        elif isinstance(value, (tuple, list)):\n"
        "            for _item in value:\n"
        "                _collect(_item)\n"
        "    for _value in list(_context.globals.values()):\n"
        "        _collect(_value)\n"
        "    for _cell in _context.graph.cells.values():\n"
        "        _collect(_cell.output)\n"
        "    for _ref in list(_context.ui_element_registry._objects.values()):\n"
        "        if isinstance(_element := _ref(), anywidget):\n"
        "            _collect(_element.widget)\n"
        "    lens_state = {\n"
        '        "live": len(_held),\n'
        '        "automatic": any(\n'
        '            _cell.namespace_to_variable("marimo") is not None\n'
        "            and contains_instance(_cell.output, _Lens)\n"
        "            for _cell in _context.graph.cells.values()\n"
        "        ),\n"
        "    }\n"
        "    return (lens_state,)\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    return path


def _lens_state(notebook: Path) -> dict[str, object]:
    result = asyncio.run(
        probe_runtime_in_worker(
            notebook,
            cell_ids=(),
            variables=("lens_state.live", "lens_state.automatic"),
            timeout=30,
        )
    )
    assert result.values.errors == {}
    return result.values.values


@pytest.mark.parametrize("lens", sorted(_AUTHORED_LENS))
def test_studio_notebook_keeps_its_authored_lens_as_the_only_lens(
    tmp_path: Path,
    lens: str,
) -> None:
    notebook = _notebook(tmp_path / "notebook.py", studio=True, lens=lens)

    assert _lens_state(notebook) == {
        "lens_state.live": 1,
        "lens_state.automatic": False,
    }


def test_studio_notebook_without_an_authored_lens_uses_marimos_automatic_lens(
    tmp_path: Path,
) -> None:
    notebook = _notebook(tmp_path / "notebook.py", studio=True, lens=None)

    assert _lens_state(notebook) == {
        "lens_state.live": 1,
        "lens_state.automatic": True,
    }


def test_notebook_outside_studio_keeps_marimos_automatic_lens(tmp_path: Path) -> None:
    notebook = _notebook(tmp_path / "notebook.py", studio=False, lens="documented")

    assert _lens_state(notebook)["lens_state.automatic"] is True


def test_lens_mount_policy_close_restores_marimos_hook() -> None:
    from marimo._runtime.runner.hooks import create_default_hooks
    from marimo._runtime.runner.hooks_lens import mount_lens

    hooks = create_default_hooks()
    policy = LensMountPolicy(
        SimpleNamespace(_kernel=SimpleNamespace(_hooks=hooks)),
        lambda: True,
    )

    policy.open()
    assert mount_lens not in hooks.post_execution_hooks
    assert mount_lens not in hooks.copy().post_execution_hooks

    policy.close()
    assert mount_lens in hooks.post_execution_hooks
