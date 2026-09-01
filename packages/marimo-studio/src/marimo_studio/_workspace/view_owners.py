"""Persist per-name view incarnations outside provider project trees."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from marimo_studio._filesystem._secure_types import FileIdentity
from marimo_studio._filesystem.io import (
    read_file_snapshot_with_identity,
    reject_mutable_symlinks,
)
from marimo_studio._filesystem.paths import validate_portable_path_component
from marimo_studio._workspace.models import (
    RESERVED_VIEW_NAMES,
    VIEW_NAME_MAX_BYTES,
    VIEW_PATTERN,
)
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.toml import parse_toml
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import ConfigurationError

VIEW_OWNER_DIRECTORY = ".owners"
_VIEW_OWNER_SCHEMA = 1
_VIEW_OWNER_SUFFIX = ".toml"
_VIEW_OWNER_GENERATION = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ViewOwner:
    """One durable per-name incarnation and its catalog presence state."""

    generation: str
    present: bool


def view_owner_path(view_root: Path, name: str) -> Path:
    """Return the Studio-owned record for one validated view name."""
    return view_root / VIEW_OWNER_DIRECTORY / f"{name}{_VIEW_OWNER_SUFFIX}"


def encode_view_owner(*, present: bool, generation: str | None = None) -> str:
    """Serialize a fresh view owner or an absent-name tombstone."""
    generation = generation or secrets.token_hex(32)
    if _VIEW_OWNER_GENERATION.fullmatch(generation) is None:
        raise ValueError(
            "View owner generation must be 64 lowercase hexadecimal characters"
        )
    document = tomlkit.document()
    document["schema"] = _VIEW_OWNER_SCHEMA
    document["generation"] = generation
    document["present"] = present
    return tomlkit.dumps(document)


def decode_view_owner(source: str, path: Path) -> ViewOwner:
    """Decode one strict Studio-owned view incarnation record."""
    data = parse_toml(source, path)
    unknown = sorted(set(data) - {"schema", "generation", "present"})
    if unknown:
        raise ConfigurationError(
            f"Unsupported view owner field {unknown[0]!r} in {path}"
        )
    if type(data.get("schema")) is not int or data["schema"] != _VIEW_OWNER_SCHEMA:
        raise ConfigurationError(f"schema must be {_VIEW_OWNER_SCHEMA} in {path}")
    generation = data.get("generation")
    if (
        not isinstance(generation, str)
        or _VIEW_OWNER_GENERATION.fullmatch(generation) is None
    ):
        raise ConfigurationError(
            f"generation must be 64 lowercase hexadecimal characters in {path}"
        )
    present = data.get("present")
    if not isinstance(present, bool):
        raise ConfigurationError(f"present must be a boolean in {path}")
    return ViewOwner(generation, present)


def _validated_record_name(path: Path) -> str:
    if path.suffix != _VIEW_OWNER_SUFFIX:
        raise ConfigurationError(f"Unexpected view owner record: {path}")
    name = path.name.removesuffix(_VIEW_OWNER_SUFFIX)
    try:
        validate_portable_path_component(
            name,
            field="View name",
            max_bytes=VIEW_NAME_MAX_BYTES,
        )
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    if VIEW_PATTERN.fullmatch(name) is None or name in RESERVED_VIEW_NAMES:
        raise ConfigurationError(f"Invalid Studio view owner name {name!r}: {path}")
    return name


def view_owner_snapshot(
    view_root: Path,
    name: str,
) -> tuple[ViewOwner | None, FileIdentity | None]:
    """Read one optional owner and its exact file identity."""
    path = view_owner_path(view_root, name)
    try:
        payload, _mode, identity = read_file_snapshot_with_identity(
            path,
            root=view_root.parent,
        )
    except FileNotFoundError:
        return None, None
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigurationError(f"View owner is not UTF-8 text: {path}") from error
    return decode_view_owner(source, path), identity


def load_view_owner(view_root: Path, name: str) -> ViewOwner:
    """Load the required owner for one current view."""
    owner, _identity = view_owner_snapshot(view_root, name)
    if owner is None:
        raise ConfigurationError(
            f"View owner record is missing: {view_owner_path(view_root, name)}"
        )
    return owner


def view_owner_transition(
    view_root: Path,
    name: str,
    *,
    present: bool,
) -> tuple[Path, str, FileIdentity | None]:
    """Plan a fresh incarnation against the current owner identity."""
    path = view_owner_path(view_root, name)
    _owner, identity = view_owner_snapshot(view_root, name)
    return path, encode_view_owner(present=present), identity


def _owner_snapshots(
    view_root: Path,
) -> dict[str, tuple[ViewOwner, FileIdentity]]:
    owners_root = view_root / VIEW_OWNER_DIRECTORY
    if not owners_root.exists():
        return {}
    reject_mutable_symlinks(view_root.parent, {view_root, owners_root})
    if not owners_root.is_dir():
        raise ConfigurationError(f"View owner path is not a directory: {owners_root}")
    owners: dict[str, tuple[ViewOwner, FileIdentity]] = {}
    for path in sorted(owners_root.iterdir(), key=lambda candidate: candidate.name):
        if path.is_symlink() or not path.is_file():
            raise ConfigurationError(f"Unexpected view owner record: {path}")
        name = _validated_record_name(path)
        owner, identity = view_owner_snapshot(view_root, name)
        if owner is None or identity is None:
            raise ConfigurationError(f"View owner changed while it was loaded: {path}")
        owners[name] = (owner, identity)
    return owners


def reconcile_view_owners(
    view_root: Path,
    names: set[str],
    *,
    refresh_names: Callable[[], set[str]] | None = None,
) -> set[str]:
    """Adopt external names and tombstone names observed as absent."""
    if not view_root.is_dir() and not names:
        return names
    if not _view_owner_writes(view_root, names)[0]:
        return names
    with workspace_catalog_lock(view_root):
        current_names = refresh_names() if refresh_names is not None else names
        writes, expected = _view_owner_writes(view_root, current_names)
        if writes:
            with ExitStack() as locks:
                for path in sorted(writes):
                    locks.enter_context(
                        view_mutation_lock(
                            view_root,
                            path.name.removesuffix(_VIEW_OWNER_SUFFIX),
                        )
                    )
                writes, expected = _view_owner_writes(view_root, current_names)
                if writes:
                    with write_file_transaction(
                        view_root.parent,
                        writes,
                        expected=expected,
                    ):
                        pass
        return current_names


def _view_owner_writes(
    view_root: Path,
    names: set[str],
) -> tuple[dict[Path, str], dict[Path, FileIdentity | None]]:
    owners = _owner_snapshots(view_root)
    writes: dict[Path, str] = {}
    expected: dict[Path, FileIdentity | None] = {}
    for name in sorted(names):
        current = owners.get(name)
        if current is not None and current[0].present:
            continue
        path = view_owner_path(view_root, name)
        writes[path] = encode_view_owner(present=True)
        expected[path] = current[1] if current is not None else None
    for name, (owner, identity) in owners.items():
        if name in names or not owner.present:
            continue
        path = view_owner_path(view_root, name)
        writes[path] = encode_view_owner(present=False)
        expected[path] = identity
    return writes, expected


def ensure_present_view_owner(view_root: Path, name: str) -> ViewOwner:
    """Adopt one externally discovered name without reconciling other names."""
    owner, identity = view_owner_snapshot(view_root, name)
    if owner is not None and owner.present:
        return owner
    with workspace_catalog_lock(view_root), view_mutation_lock(view_root, name):
        owner, identity = view_owner_snapshot(view_root, name)
        if owner is not None and owner.present:
            return owner
        path = view_owner_path(view_root, name)
        source = encode_view_owner(present=True)
        with write_file_transaction(
            view_root.parent,
            {path: source},
            expected={path: identity},
        ):
            pass
        return decode_view_owner(source, path)
