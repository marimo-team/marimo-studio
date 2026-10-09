"""Carry a marimo-export representation as marimo output data.

The browser notebook runs this module from source, so it imports only the
standard library.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marimo_export.values import Representation

MIMEBUNDLE = "application/vnd.marimo+mimebundle"


def media_output(representation: Representation) -> tuple[str, str]:
    """Return a representation as the mimetype and data of a marimo output.

    The data is a base64 data URL, which marimo's renderer shows for images.
    An image with a display size travels in a marimo mimebundle that carries
    the size, as marimo sends its own high-density figures.
    """
    media_type = representation.media_type
    encoded = base64.b64encode(representation.data).decode("ascii")
    url = f"data:{media_type};base64,{encoded}"
    size = {
        name: pixels
        for name, pixels in (
            ("width", representation.width),
            ("height", representation.height),
        )
        if pixels is not None
    }
    if not size:
        return media_type, url
    bundle = {media_type: url, "__metadata__": {media_type: size}}
    return MIMEBUNDLE, json.dumps(bundle, separators=(",", ":"))
