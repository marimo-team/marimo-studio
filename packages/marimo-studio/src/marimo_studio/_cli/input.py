"""Read bounded text input for CLI source mutations."""

from typing import BinaryIO

from marimo_studio._views.sources import SOURCE_DOCUMENT_MAX_BYTES
from marimo_studio.errors import SourceEncodingError, SourceTooLargeError


def read_source_input(source: BinaryIO) -> str:
    """Return bounded UTF-8 source from a Click file input."""
    payload = source.read(SOURCE_DOCUMENT_MAX_BYTES + 1)
    if len(payload) > SOURCE_DOCUMENT_MAX_BYTES:
        raise SourceTooLargeError(
            f"Replacement source exceeds the {SOURCE_DOCUMENT_MAX_BYTES}-byte limit."
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceEncodingError("Replacement source must be UTF-8 text.") from error
