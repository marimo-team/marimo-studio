"""Select the notebook's Lens or own one for development output rendering."""

from collections.abc import Mapping
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from marimo_studio._projections import STUDIO_RESULT_SELECTOR

_OWNER = "__marimo_studio_lens__"


class LensOverlay:
    def __init__(self, context: Any) -> None:
        self._context = context
        self._owned: Any = None

    def __call__(self, namespace: Mapping[str, object]) -> Mapping[str, object]:
        from marimo._plugins.ui._impl.from_anywidget import anywidget
        from marimo._types.ids import CellId_t

        if find_spec("marimo_lens") is None:
            return {}
        lens_type = import_module("marimo_lens").Lens
        values = (
            *namespace.values(),
            *(
                element.widget
                for ref in tuple(self._context.ui_element_registry._objects.values())
                if isinstance(element := ref(), anywidget)
            ),
        )
        for value in values:
            if (
                isinstance(value, lens_type)
                and value is not self._owned
                and getattr(value, "comm", None) is not None
            ):
                self.close()
                return {"lens": value}
        if self._owned is None or self._owned.comm is None:
            with self._context.with_cell_id(CellId_t(_OWNER)):
                self._owned = lens_type(dom_selector=STUDIO_RESULT_SELECTOR)
        return {"lens": self._owned}

    def close(self) -> None:
        if self._owned is not None:
            self._owned.close()
            self._owned = None
            self._context.cell_lifecycle_registry.dispose(_OWNER, deletion=True)
