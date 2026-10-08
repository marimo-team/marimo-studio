"""Format starter source for Deno framework projects."""

from __future__ import annotations

import json


def typescript_string_array(values: tuple[str, ...], *, indent: str = "") -> str:
    """Render strings in the stable multiline form accepted by Deno fmt."""
    items = "".join(
        f"{indent}  {json.dumps(value, ensure_ascii=False)},\n" for value in values
    )
    return f"[\n{items}{indent}]"
