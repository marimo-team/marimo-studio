"""Capture stable source revisions for authored Studio views."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._workspace.models import StudioWorkspace, View
from marimo_studio.errors import ConfigurationError, TemplateError


def _configuration_identity(studio: StudioWorkspace) -> tuple[object, ...]:
    return (
        str(studio.config_path),
        studio.config_source,
        str(studio.notebook),
        str(studio.view_root),
        studio.default_view,
        studio.default_runtime,
        studio.runtimes,
        studio.preserve_session,
        studio.show_cell_logs,
        tuple((name, str(item.root)) for name, item in studio.views.items()),
        tuple(
            (alias, str(reference)) for alias, reference in sorted(studio.cells.items())
        ),
    )


def _asset_identity(view: View) -> tuple[tuple[object, ...], ...]:
    identity: list[tuple[object, ...]] = []
    for path in sorted(view.root.rglob("*")):
        if path == view.template or path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(view.root).as_posix()
        identity.append(
            (
                relative,
                "sha256",
                _file_digest(path),
            )
        )
    return tuple(identity)


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StudioSourceSnapshot:
    """UTF-8 source text and content identities captured in one filesystem pass."""

    documents: dict[str, str]
    notebook_source: str
    base_identity: tuple[object, ...]
    document_identities: dict[str, str]
    asset_identities: dict[str, tuple[tuple[object, ...], ...]]

    def revision(self, view_name: str) -> str:
        identity = (
            view_name,
            self.base_identity,
            self.document_identities[view_name],
            self.asset_identities[view_name],
        )
        return hashlib.sha256(repr(identity).encode()).hexdigest()

    @property
    def revisions(self) -> dict[str, str]:
        return {name: self.revision(name) for name in self.documents}


def capture_studio_sources(
    studio: StudioWorkspace,
    view_names: tuple[str, ...] | None = None,
) -> StudioSourceSnapshot:
    """Read shared sources and the selected views in one filesystem pass."""
    selected = (
        tuple(studio.views) if view_names is None else tuple(dict.fromkeys(view_names))
    )
    unknown = set(selected).difference(studio.views)
    if unknown:
        raise ConfigurationError(f"Unknown view {sorted(unknown)[0]!r}")
    paths = tuple(
        dict.fromkeys(
            (
                studio.config_path,
                studio.notebook,
                *(studio.views[name].template for name in selected),
            )
        )
    )
    contents = {path: path.read_bytes() for path in paths}
    documents: dict[str, str] = {}
    for name in selected:
        view = studio.views[name]
        try:
            documents[name] = contents[view.template].decode("utf-8")
        except UnicodeDecodeError as error:
            raise TemplateError(
                f"Could not decode {view.template} as UTF-8: {error}",
                source=view.template,
            ) from error
    try:
        notebook_source = contents[studio.notebook].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError(
            f"Could not decode {studio.notebook} as UTF-8: {error}"
        ) from error
    shared_paths = tuple(dict.fromkeys((studio.config_path, studio.notebook)))
    source_identity = tuple(
        (str(path), hashlib.sha256(contents[path]).hexdigest()) for path in shared_paths
    )
    return StudioSourceSnapshot(
        documents=documents,
        notebook_source=notebook_source,
        base_identity=(_configuration_identity(studio), source_identity),
        document_identities={
            name: hashlib.sha256(contents[studio.views[name].template]).hexdigest()
            for name in selected
        },
        asset_identities={
            name: _asset_identity(studio.views[name]) for name in selected
        },
    )


__all__ = ["StudioSourceSnapshot", "capture_studio_sources"]
