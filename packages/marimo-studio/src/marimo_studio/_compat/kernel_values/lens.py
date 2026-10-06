"""Share one notebook Lens between the notebook and Studio's preview."""

from collections.abc import Mapping


def lens_overlay(namespace: Mapping[str, object]) -> Mapping[str, object]:
    del namespace
    try:
        from marimo_lens import notebook_lens
    except ImportError:
        return {}

    lens = notebook_lens()
    return {} if lens is None else {"lens": lens}
