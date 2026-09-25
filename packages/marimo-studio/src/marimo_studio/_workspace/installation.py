"""Resolve the installation of the Studio running this process."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import url2pathname

STUDIO_DISTRIBUTION = "marimo-studio"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class InvokingStudio:
    """The source that installs the Studio running this process.

    Processes that must import the same Studio, such as a notebook environment
    or a sandboxed kernel, install this source because a published release with
    the same version number can carry different code and dependency pins.
    """

    version: str
    editable: Path | None = None
    url: str | None = None
    """PEP 508 direct reference for an archive, a directory, or a VCS commit."""

    @property
    def requirement(self) -> str:
        """Return the requirement in the form Marimo's runtime overlay accepts."""
        if self.editable is not None:
            return f"-e {self.editable}"
        if self.url is not None:
            return f"{STUDIO_DISTRIBUTION} @ {self.url}"
        return f"{STUDIO_DISTRIBUTION}=={self.version}"


def invoking_studio() -> InvokingStudio | None:
    """Return the running Studio's source, or `None` without installed metadata."""
    try:
        installed = distribution(STUDIO_DISTRIBUTION)
    except PackageNotFoundError:
        return None
    version = installed.version
    recorded = installed.read_text("direct_url.json")
    if recorded is None:
        return InvokingStudio(version)
    try:
        direct_url = json.loads(recorded)
        url = str(direct_url["url"])
        vcs = direct_url.get("vcs_info")
        editable = bool(direct_url.get("dir_info", {}).get("editable"))
    except (AttributeError, KeyError, TypeError, ValueError):
        _LOGGER.warning("Ignoring unreadable marimo-studio direct_url.json")
        return InvokingStudio(version)
    if isinstance(vcs, dict):
        kind, commit = vcs.get("vcs"), vcs.get("commit_id")
        if kind and commit:
            return InvokingStudio(version, url=f"{kind}+{url}@{commit}")
        return InvokingStudio(version)
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return InvokingStudio(version, url=url)
    path = _local_path(parsed.netloc, parsed.path)
    if path is None or not (path.is_dir() if editable else path.exists()):
        _LOGGER.warning(
            "marimo-studio was installed from %s, which is no longer available. "
            "Using marimo-studio==%s instead.",
            url,
            version,
        )
        return InvokingStudio(version)
    if editable:
        return InvokingStudio(version, editable=path)
    return InvokingStudio(version, url=url)


def _local_path(authority: str, path: str) -> Path | None:
    # A network share keeps its host in the URL authority.
    share = authority not in ("", "localhost")
    try:
        return Path(url2pathname(f"//{authority}{path}" if share else path))
    except URLError:
        return None
