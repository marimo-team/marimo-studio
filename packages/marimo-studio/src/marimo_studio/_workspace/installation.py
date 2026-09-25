"""Locate the local source of the running Studio installation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

STUDIO_DISTRIBUTION = "marimo-studio"


@dataclass(frozen=True)
class LocalStudioSource:
    """A checkout or archive on this machine that the running Studio came from."""

    url: str
    path: Path
    editable: bool


def local_studio_source() -> LocalStudioSource | None:
    """Return the local source the installer recorded, or `None` for an index install.

    Processes that must import the same Studio, such as a notebook environment
    or a sandboxed kernel, install this source because a published release with
    the same version number can carry different code and dependency pins.
    """
    try:
        recorded = distribution(STUDIO_DISTRIBUTION).read_text("direct_url.json")
    except PackageNotFoundError:
        return None
    if recorded is None:
        return None
    direct_url = json.loads(recorded)
    url = str(direct_url.get("url", ""))
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    # A network share keeps its host in the URL authority.
    share = parsed.netloc not in ("", "localhost")
    path = Path(
        url2pathname(f"//{parsed.netloc}{parsed.path}" if share else parsed.path)
    )
    editable = bool(direct_url.get("dir_info", {}).get("editable"))
    if not (path.is_dir() if editable else path.exists()):
        return None
    return LocalStudioSource(url=url, path=path, editable=editable)
