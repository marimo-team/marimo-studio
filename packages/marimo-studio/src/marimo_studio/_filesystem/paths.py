"""Validate portable filesystem path components and project-relative paths."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from unicodedata import category, normalize

PORTABLE_PATH_COMPONENT_MAX_BYTES = 255

_WINDOWS_DEVICE_NAME = re.compile(
    r"(?:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?",
    re.IGNORECASE,
)
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"|?*')


def validate_portable_path_component(
    value: object,
    *,
    field: str,
    max_bytes: int = PORTABLE_PATH_COMPONENT_MAX_BYTES,
) -> str:
    """Return one cross-platform, bounded filesystem component."""
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"{field} must be one portable path component")
    if any(category(character) == "Cc" for character in value):
        raise ValueError(f"{field} must not contain control characters")
    if normalize("NFC", value) != value:
        raise ValueError(f"{field} must use NFC Unicode normalization")
    if value.endswith((".", " ")):
        raise ValueError(f"{field} must not end with a dot or space")
    if any(character in _WINDOWS_FORBIDDEN_CHARACTERS for character in value):
        raise ValueError(f"{field} contains a cross-platform forbidden character")
    if _WINDOWS_DEVICE_NAME.fullmatch(value) is not None:
        raise ValueError(f"{field} contains a reserved Windows device name")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} exceeds the {max_bytes}-byte limit")
    return value


def validate_relative_path(
    value: object,
    *,
    field: str,
) -> PurePosixPath:
    if not isinstance(value, (str, PurePosixPath)):
        raise ValueError(f"{field} must be a project-relative POSIX path")
    raw = str(value)
    if not raw or raw.startswith("/") or "\\" in raw:
        raise ValueError(f"{field} must be a normalized project-relative POSIX path")
    if PureWindowsPath(raw).drive:
        raise ValueError(f"{field} must not use a Windows drive prefix")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} must be a normalized project-relative POSIX path")
    for part in parts:
        validate_portable_path_component(part, field=f"{field} path segment")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() != raw:
        raise ValueError(f"{field} must be a normalized project-relative POSIX path")
    return path
