"""Read the sandbox context that marimohub gives a notebook session.

marimohub sets ``MARIMOHUB_CONTEXT_FILE`` before marimo starts and writes the
JSON document once the session's browser address is known. The document is
written atomically and stays fixed for the process lifetime, so a parsed file is
cached. The file can be missing during startup and outside marimohub.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard, get_args
from urllib.parse import urlsplit

from marimo_studio._views.records import HostPersistence

CONTEXT_FILE_ENV = "MARIMOHUB_CONTEXT_FILE"
_SCHEMA_VERSION = 1
_MAX_BYTES = 64 * 1024
_LOGGER = logging.getLogger("marimo.studio")


@dataclass(frozen=True)
class SandboxContext:
    """Describe how marimohub publishes this notebook's marimo server.

    A field that the hub reports with an unknown value reads as unknown, so a
    newer hub keeps the fields that Studio understands.
    """

    public_url: str | None
    """Browser address of the marimo server root, ending with ``/``."""
    host_origin: bool
    """The server shares the hub page's origin and sign-in."""
    persistence: HostPersistence | None


_contexts: dict[str, SandboxContext | None] = {}


def sandbox_context(
    environ: Mapping[str, str] = os.environ,
) -> SandboxContext | None:
    """Return the sandbox context, or ``None`` when no valid file exists."""
    path = environ.get(CONTEXT_FILE_ENV, "")
    if not path:
        return None
    if path in _contexts:
        return _contexts[path]
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(_MAX_BYTES + 1)
    except OSError:
        return None
    context = _parse(path, raw)
    _contexts[path] = context
    return context


def host_persistence() -> HostPersistence | None:
    """Return what the hub saves when the session ends, when it reports it."""
    context = sandbox_context()
    return context.persistence if context is not None else None


def published_url(url: str, server_url: str) -> str:
    """Return a code-mode ``url`` on the hub's public address.

    ``server_url`` is the address that code mode gives for its own marimo
    server. Its path must match the published base path, which keeps the
    session's token path in proxy exposure.
    """
    context = sandbox_context()
    if context is None or context.public_url is None:
        return url
    root = server_url.rstrip("/")
    if urlsplit(root).path != urlsplit(context.public_url).path.rstrip("/"):
        return url
    if url != root and not url.startswith(f"{root}/"):
        return url
    return context.public_url + url[len(root) :].lstrip("/")


def _parse(path: str, raw: bytes) -> SandboxContext | None:
    record: object = None
    if len(raw) <= _MAX_BYTES:
        with suppress(ValueError, RecursionError):
            record = json.loads(raw)
    if not isinstance(record, dict) or not _current_schema(
        record.get("schema_version")
    ):
        _LOGGER.warning(
            "Ignoring the marimohub sandbox context at %s because it is not a "
            "schema %s JSON document.",
            path,
            _SCHEMA_VERSION,
        )
        return None
    public_url = record.get("public_url")
    persistence = record.get("persistence_mode")
    context = SandboxContext(
        public_url=(
            (public_url if public_url.endswith("/") else f"{public_url}/")
            if _public_url(public_url)
            else None
        ),
        host_origin=record.get("exposure_mode") == "proxy",
        persistence=persistence if persistence in get_args(HostPersistence) else None,
    )
    unknown = [
        field
        for field, known in (
            ("public_url", context.public_url is not None),
            ("exposure_mode", record.get("exposure_mode") in {"subdomain", "proxy"}),
            ("persistence_mode", context.persistence is not None),
        )
        if not known
    ]
    if unknown:
        _LOGGER.warning(
            "Ignoring %s in the marimohub sandbox context at %s. Studio does not "
            "recognize the reported values.",
            ", ".join(unknown),
            path,
        )
    return context


def _current_schema(value: object) -> bool:
    return type(value) is int and value == _SCHEMA_VERSION


def _public_url(value: object) -> TypeGuard[str]:
    # marimohub publishes a bare HTTP(S) root. Credentials, a query, or a
    # fragment cannot prefix a view path.
    if not isinstance(value, str) or "?" in value or "#" in value:
        return False
    try:
        parts = urlsplit(value)
        _ = parts.port  # Reading the port validates it.
    except ValueError:
        return False
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and "@" not in parts.netloc
    )
