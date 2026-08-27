"""Convert authored 0.0.6 view directories to required manifests."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._filesystem.io import read_text, reject_mutable_symlinks
from marimo_studio._filesystem.tree import bounded_regular_files
from marimo_studio._views.create import _workspace_ignore_source
from marimo_studio._workspace.config import (
    load_studio_definition,
    validate_view_name,
)
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers._document import (
    HTMLDocumentParser,
    validate_self_contained_html,
)
from marimo_studio.view_providers._host.package_policy import VANILLA_PROVIDER_ID

_LEGACY_GENERATED_ROOTS = (".artifacts", ".locks")


@dataclass(frozen=True)
class WorkspaceMigrationResult:
    """Describe one manifest conversion for authored view directories."""

    notebook: Path
    view_root: Path
    views: tuple[str, ...]
    created: tuple[Path, ...]
    updated: tuple[Path, ...]
    dry_run: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "view_root": str(self.view_root),
            "views": list(self.views),
            "created": [str(path) for path in self.created],
            "updated": [str(path) for path in self.updated],
            "dry_run": self.dry_run,
        }


def _legacy_views(notebook: Path, view_root: Path) -> tuple[Path, ...]:
    if not view_root.is_dir():
        return ()
    candidates: list[Path] = []
    for directory in sorted(view_root.iterdir(), key=lambda path: path.name):
        if directory.name.startswith(".") or not directory.is_dir():
            continue
        manifest = directory / "view.toml"
        if manifest.is_file():
            continue
        entrypoint = directory / "index.html"
        if not entrypoint.is_file():
            continue
        validate_view_name(directory.name)
        reject_mutable_symlinks(
            notebook.parent,
            {view_root, directory, entrypoint, manifest},
        )
        authored = bounded_regular_files(
            directory,
            max_files=4_096,
            label=f"Legacy view {directory.name!r}",
            excluded_roots=_LEGACY_GENERATED_ROOTS,
        )
        additional = next((path for path in authored if path != entrypoint), None)
        if additional is not None:
            relative = additional.relative_to(directory).as_posix()
            raise ViewProjectError(
                f"Legacy view {directory.name!r} contains authored file "
                f"{relative!r}. Inline or remove the sibling file before "
                "migrating, or create another view with a provider for "
                "multi-file projects.",
                source=additional,
            )
        parser = HTMLDocumentParser()
        try:
            source = read_text(entrypoint)
        except UnicodeError as error:
            raise ViewProjectError(
                f"Legacy view {directory.name!r} entry document must be UTF-8.",
                source=entrypoint,
            ) from error
        except OSError as error:
            raise ViewProjectError(
                f"Legacy view {directory.name!r} entry document is unavailable.",
                source=entrypoint,
            ) from error
        try:
            parser.feed(source)
            validate_self_contained_html(parser, entrypoint.as_posix())
        except ViewProjectError as error:
            if error.source is not None:
                raise
            raise error.with_source(entrypoint) from error
        candidates.append(directory)
    return tuple(candidates)


def _migration_writes(
    view_root: Path,
    candidates: tuple[Path, ...],
) -> dict[Path, str]:
    writes = {
        directory / "view.toml": encode_view_manifest(VANILLA_PROVIDER_ID)
        for directory in candidates
    }
    ignore = view_root / ".gitignore"
    ignore_source = _workspace_ignore_source(ignore)
    if candidates and (not ignore.is_file() or read_text(ignore) != ignore_source):
        writes[ignore] = ignore_source
    return writes


def _classify_writes(
    writes: dict[Path, str],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    created = tuple(sorted(path for path in writes if not path.exists()))
    updated = tuple(sorted(path for path in writes if path.exists()))
    return created, updated


def migrate_workspace(
    notebook: str | Path,
    *,
    dry_run: bool = False,
) -> WorkspaceMigrationResult:
    """Add required manifests to authored 0.0.6 view directories."""
    notebook_path = Path(notebook).expanduser().resolve()
    definition = load_studio_definition(notebook_path)
    view_root = definition.view_root
    reject_mutable_symlinks(notebook_path.parent, {view_root})
    if dry_run:
        candidates = _legacy_views(notebook_path, view_root)
        writes = _migration_writes(view_root, candidates)
        created, updated = _classify_writes(writes)
        return WorkspaceMigrationResult(
            notebook=notebook_path,
            view_root=view_root,
            views=tuple(directory.name for directory in candidates),
            created=created,
            updated=updated,
            dry_run=True,
        )
    with workspace_catalog_lock(view_root):
        definition = load_studio_definition(notebook_path)
        candidates = _legacy_views(notebook_path, definition.view_root)
        with ExitStack() as locks:
            for directory in candidates:
                locks.enter_context(view_mutation_lock(view_root, directory.name))
            candidates = _legacy_views(notebook_path, definition.view_root)
            writes = _migration_writes(view_root, candidates)
            created, updated = _classify_writes(writes)
            if writes:
                with write_file_transaction(notebook_path.parent, writes):
                    pass
    return WorkspaceMigrationResult(
        notebook=notebook_path,
        view_root=view_root,
        views=tuple(directory.name for directory in candidates),
        created=created,
        updated=updated,
        dry_run=False,
    )
