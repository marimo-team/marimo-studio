"""Inspect, copy, and render files used by Deno provider projects."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

from marimo_studio._artifacts.limits import PROJECT_INPUT_BUDGET
from marimo_studio._filesystem.tree import bounded_regular_files
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.provider_runner import ProviderCommandError
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    ProviderCancellation,
    SourceDocument,
    ViewProject,
)

_TEMPLATE_EXCLUDES = frozenset(
    {".artifacts", ".deno", ".vite", "dist", "node_modules", "__pycache__"}
)


def project_inventory(
    project: ViewProject,
    roots: tuple[str, ...],
    editor_languages: Mapping[str, str],
    *,
    read_only: frozenset[str] = frozenset(),
) -> tuple[SourceDocument, ...]:
    """Return ordered editor documents for provider-owned roots."""
    return _project_inventory(project, roots, editor_languages, read_only)


def _project_inventory(
    project: ViewProject,
    roots: tuple[str, ...],
    editor_languages: Mapping[str, str],
    read_only: frozenset[str],
) -> tuple[SourceDocument, ...]:
    cancellation = current_provider_cancellation()
    files: list[Path] = []
    seen_files: set[Path] = set()
    seen_entries: set[Path] = set()

    def add_entry(path: Path) -> bool:
        key = path.absolute()
        if key in seen_entries:
            return False
        seen_entries.add(key)
        if len(seen_entries) > PROJECT_INPUT_BUDGET.max_files:
            raise ValueError(
                "Deno project contains more than "
                f"{PROJECT_INPUT_BUDGET.max_files} entries. "
                "Remove files or split the project."
            )
        return True

    def add_file(path: Path) -> None:
        key = path.absolute()
        if not add_entry(path) or key in seen_files:
            return
        seen_files.add(key)
        files.append(path)

    for name in roots:
        if cancellation is not None and cancellation.cancelled:
            raise ProviderCommandError("Deno project inspection was cancelled")
        path = project.root / name
        if not path.exists():
            continue
        if path.is_symlink():
            raise ValueError(f"View project input is a symlink: {path}")
        if path.is_file():
            add_file(path)
            continue
        if not add_entry(path):
            continue
        try:
            discovered = bounded_regular_files(
                path,
                max_files=PROJECT_INPUT_BUDGET.max_files,
                label="Deno project",
                seen=seen_files,
                seen_entries=seen_entries,
                cancelled=(
                    (lambda: cancellation.cancelled)
                    if cancellation is not None
                    else None
                ),
            )
        except ConfigurationError as error:
            raise ValueError(str(error)) from error
        files.extend(sorted(discovered, key=str))
    editor_documents: list[SourceDocument] = []
    for path in dict.fromkeys(files):
        relative = PurePosixPath(path.relative_to(project.root).as_posix())
        language = editor_languages.get(
            path.name,
            editor_languages.get(path.suffix.lower()),
        )
        if language is not None:
            access = "read" if relative.as_posix() in read_only else "edit"
            editor_documents.append(SourceDocument(relative, language, access))
    return tuple(editor_documents)


def copy_project_inputs(
    project: ViewProject,
    inputs: tuple[PurePosixPath, ...],
    destination: Path,
    cancellation: ProviderCancellation | None = None,
) -> None:
    """Copy declared inputs into a fresh provider work directory."""
    _copy_project_inputs(project, inputs, destination, cancellation)


def _copy_project_inputs(
    project: ViewProject,
    inputs: tuple[PurePosixPath, ...],
    destination: Path,
    cancellation: ProviderCancellation | None,
) -> None:
    if cancellation is not None and cancellation.cancelled:
        raise ProviderCommandError("Deno source staging was cancelled")
    destination.mkdir(parents=True, exist_ok=False)
    for path in inputs:
        if cancellation is not None and cancellation.cancelled:
            raise ProviderCommandError("Deno source staging was cancelled")
        source = project.root.joinpath(*path.parts)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"View project input is unavailable: {source}")
        target = destination.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if cancellation is not None and cancellation.cancelled:
        raise ProviderCommandError("Deno source staging was cancelled")


def template_files(
    package: str,
    replacements: Mapping[str, str],
) -> dict[PurePosixPath, bytes]:
    """Render one packaged text template tree."""
    root = resources.files(package).joinpath("template")
    files: dict[PurePosixPath, bytes] = {}

    def visit(node: Traversable, prefix: PurePosixPath) -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            if child.name in _TEMPLATE_EXCLUDES:
                continue
            relative = prefix / child.name
            if child.is_dir():
                visit(child, relative)
                continue
            content = child.read_text(encoding="utf-8")
            for marker, value in replacements.items():
                content = content.replace(marker, value)
            files[relative] = content.encode()

    visit(root, PurePosixPath())
    return files
