from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from marimo_studio._compat.kernel_values.lens import lens_overlay
from marimo_studio._compat.kernel_values.outputs import KernelOutputRenderer
from marimo_studio._compat.kernel_values.session import _parse_output_result
from marimo_studio._projections.runtime_records import (
    RuntimeProbe,
    ValueReadResult,
    runtime_probe_from_dict,
)

from .values_test_support import (
    _native_output_context,
    _resource_element_class,
    assert_native_resources_released,
)


def test_lens_overlay_shows_the_notebooks_open_lens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marimo_lens = pytest.importorskip("marimo_lens")
    from marimo._types.ids import CellId_t

    context = _native_output_context()
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification", lambda _: None
    )
    try:
        with context.install():
            assert lens_overlay({}) == {}
            # marimo writes widget code to a virtual file only while a cell runs.
            with context.with_cell_id(CellId_t("lens-cell")):
                lens = marimo_lens.Lens()
            assert lens_overlay({})["lens"] is lens
            lens.close()
            assert lens_overlay({}) == {}
    finally:
        context.virtual_file_registry.shutdown()


def test_lens_overlay_is_empty_without_marimo_lens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "marimo_lens", None)

    assert lens_overlay({}) == {}


def test_output_callback_retains_overlay_resources_and_uses_the_output_wire_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from marimo._runtime.virtual_file.virtual_file import VirtualFileLifecycleItem

    context = _native_output_context()
    ResourceElement = _resource_element_class()

    class Display:
        def __init__(self) -> None:
            self.element: Any = None

        def _mime_(self) -> tuple[str, str]:
            if self.element is None:
                file = VirtualFileLifecycleItem(ext="txt", buffer=b"overlay")
                file.add_to_cell_lifecycle_registry()
                self.element = ResourceElement(file.virtual_file.url)
            return "text/html", self.element.text

    values = {"inspector-panel": Display()}
    renderer = KernelOutputRenderer(context, overlays=lambda _: values)
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification", lambda _: None
    )
    try:
        with context.install():

            def read():
                return renderer.render(
                    {}, {}, (), {}, consumer_id="view", max_output_bytes=10_000
                )

            first = read()
            assert first.overlays and first.outputs == {} and first.errors == {}
            assert _parse_output_result(first.to_dict()) == first
            probe = RuntimeProbe({}, ValueReadResult({}, {}), first)
            assert runtime_probe_from_dict(probe.to_dict()) == probe
            assert read().overlays == first.overlays
            values.clear()
            assert read().overlays == {}
            renderer.close()
            renderer.close()
            assert_native_resources_released(context)
    finally:
        context.virtual_file_registry.shutdown()


@pytest.mark.parametrize("edit", [False, True])
def test_kernel_overlays_are_development_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edit: bool
) -> None:
    import marimo as mo
    from marimo._session.model import SessionMode

    import marimo_studio._compat.kernel_values.kernel as kernel

    context = _native_output_context()
    context.session_mode = SessionMode.EDIT if edit else SessionMode.RUN
    context._kernel = SimpleNamespace(app_metadata=SimpleNamespace(filename=None))
    monkeypatch.setattr(kernel, "discover_studio_definition", lambda _: object())
    monkeypatch.setattr(kernel, "keep_cached_cells_compatible", lambda: lambda: None)
    monkeypatch.setattr(
        kernel, "ObservationLedger", lambda _: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(kernel, "install_observation_ledger", lambda *_: lambda: None)

    inspector = mo.md("Inspector")
    monkeypatch.setattr(
        kernel, "lens_overlay", lambda _namespace: {"inspector-panel": inspector}
    )
    bridge = kernel._KernelBridgeLifespan()
    try:
        with context.install():
            assert bridge._activate(context, tmp_path / "notebook.py", None)
            assert bridge._output_renderer is not None
            result = bridge._output_renderer.render(
                {}, {}, (), {}, consumer_id="view", max_output_bytes=10_000
            )
            assert bool(result.overlays) is edit
            bridge._close()
    finally:
        context.virtual_file_registry.shutdown()
