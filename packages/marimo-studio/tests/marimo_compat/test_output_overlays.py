from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from marimo_studio._compat.kernel_values.lens import LensOverlay
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


def test_optional_lens_reuses_notebook_instances_and_closes_only_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Lens:
        def __init__(self, **kwargs: object) -> None:
            self.comm: object | None = object()
            self.options = kwargs

        def close(self) -> None:
            self.comm = None

    context = SimpleNamespace(
        with_cell_id=lambda _: nullcontext(),
        ui_element_registry=SimpleNamespace(_objects={}),
        cell_lifecycle_registry=SimpleNamespace(dispose=lambda *_args, **_kwargs: None),
    )
    module = "marimo_studio._compat.kernel_values.lens"
    monkeypatch.setattr(f"{module}.find_spec", lambda _: None)
    overlay = LensOverlay(context)
    assert overlay({}) == {}
    monkeypatch.setattr(f"{module}.find_spec", lambda _: object())
    monkeypatch.setattr(f"{module}.import_module", lambda _: SimpleNamespace(Lens=Lens))
    owned = overlay({})["lens"]
    assert isinstance(owned, Lens)
    assert overlay({})["lens"] is owned
    authored = Lens(dom_selector="#custom")
    assert overlay({"lens": authored})["lens"] is authored
    assert authored.options == {"dom_selector": "#custom"}
    assert owned.comm is None
    authored.close()
    fallback = overlay({"lens": authored})["lens"]
    assert isinstance(fallback, Lens) and fallback is not owned
    replacement = Lens()
    assert overlay({"lens": replacement})["lens"] is replacement
    overlay.close()
    assert fallback.comm is None
    assert replacement.comm is not None


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
                    {}, (), (), set(), consumer_id="view", max_output_bytes=10_000
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

    class Overlay:
        def __init__(self, _context):
            self.value = mo.md("Inspector")

        def __call__(self, _namespace):
            return {"inspector-panel": self.value}

        def close(self):
            pass

    monkeypatch.setattr(kernel, "LensOverlay", Overlay)
    bridge = kernel._KernelBridgeLifespan()
    try:
        with context.install():
            assert bridge._activate(context, tmp_path / "notebook.py", None)
            assert bridge._output_renderer is not None
            result = bridge._output_renderer.render(
                {}, (), (), set(), consumer_id="view", max_output_bytes=10_000
            )
            assert bool(result.overlays) is edit
            bridge._close()
    finally:
        context.virtual_file_registry.shutdown()
