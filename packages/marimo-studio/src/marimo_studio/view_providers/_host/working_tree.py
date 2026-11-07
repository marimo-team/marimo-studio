"""Identify provider code installed from a local directory.

An editable or directory install keeps its distribution version while its
code changes. Build provenance records a digest of such a provider's package
file metadata, so an edit to the provider reaches the next build. An install
from an index, archive, or VCS URL keeps version identity.
"""

from __future__ import annotations

import hashlib
import json
import os
from importlib.metadata import EntryPoint
from importlib.util import find_spec
from pathlib import Path


def working_tree_source(point: EntryPoint) -> tuple[Path, ...]:
    """Return the package paths of a provider installed from a directory.

    `direct_url.json` marks a directory install with `dir_info`. The paths
    are the import locations of the first regular package or module on the
    entry point's module path, which an editable install resolves to the
    working tree. Namespace packages above it are shared with other
    distributions, so they are skipped. Finding the package runs import
    finders and executes no provider code.
    """
    distribution = point.dist
    if distribution is None:
        return ()
    try:
        direct_url = json.loads(distribution.read_text("direct_url.json") or "null")
    except ValueError:
        return ()
    if not isinstance(direct_url, dict) or "dir_info" not in direct_url:
        return ()
    parts = point.module.split(".")
    for depth in range(1, len(parts) + 1):
        try:
            spec = find_spec(".".join(parts[:depth]))
        except (ImportError, ValueError):
            return ()
        if spec is None:
            return ()
        if spec.origin is not None:
            locations = spec.submodule_search_locations
            if locations is None:
                return (Path(spec.origin),)
            return tuple(Path(item) for item in locations)
    return ()


def source_digest(paths: tuple[Path, ...]) -> str | None:
    """Digest the metadata of each file beneath `paths`, or return None.

    Each entry records the file's relative path, size, modification and
    change times, and inode, which every edit or replacement changes. Reading
    metadata keeps the digest cheap for packages that ship large assets.
    """
    if not paths:
        return None
    entries: list[tuple[int, str, int, int, int, int]] = []
    for index, root in enumerate(paths):
        if root.is_file():
            files = [(root.name, root)]
        else:
            files = []
            for directory, names, filenames in os.walk(root):
                names[:] = [name for name in names if name != "__pycache__"]
                files.extend(
                    (
                        Path(directory, filename).relative_to(root).as_posix(),
                        Path(directory, filename),
                    )
                    for filename in filenames
                )
        for name, path in files:
            try:
                state = path.stat()
            except OSError:
                # A file removed during the walk leaves the next digest to
                # describe the settled tree.
                continue
            entries.append(
                (
                    index,
                    name,
                    state.st_size,
                    state.st_mtime_ns,
                    state.st_ctime_ns,
                    state.st_ino,
                )
            )
    payload = json.dumps(sorted(entries), separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
