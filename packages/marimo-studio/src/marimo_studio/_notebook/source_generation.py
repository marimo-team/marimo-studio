"""Bind notebook execution to one stable saved-file generation."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._filesystem.io import read_bytes
from marimo_studio.errors import ConfigurationError


@dataclass(frozen=True)
class NotebookSourceGeneration:
    revision: str
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "size": self.size,
            "mtimeNs": self.mtime_ns,
            "ctimeNs": self.ctime_ns,
        }

    @classmethod
    def from_dict(cls, value: object) -> NotebookSourceGeneration:
        if not isinstance(value, dict) or set(value) != {
            "revision",
            "device",
            "inode",
            "mode",
            "size",
            "mtimeNs",
            "ctimeNs",
        }:
            raise ValueError("Notebook source generation is invalid")
        revision = value["revision"]
        fields = tuple(
            value[name]
            for name in ("device", "inode", "mode", "size", "mtimeNs", "ctimeNs")
        )
        if (
            not isinstance(revision, str)
            or len(revision) != 64
            or any(character not in "0123456789abcdef" for character in revision)
            or any(type(field) is not int or field < 0 for field in fields)
        ):
            raise ValueError("Notebook source generation is invalid")
        return cls(revision, *fields)


def capture_notebook_source_generation(
    path: Path,
    expected_revision: str,
) -> NotebookSourceGeneration:
    """Return stable file state for the expected saved notebook source."""
    try:
        before = os.stat(path)
        payload = read_bytes(path, root=path.parent)
        after = os.stat(path)
    except OSError as error:
        raise ConfigurationError(
            f"Notebook changed during inspection: {path}. Retry the request."
        ) from error
    state_before = _state(before)
    state_after = _state(after)
    revision = hashlib.sha256(payload).hexdigest()
    if state_before != state_after or revision != expected_revision:
        raise ConfigurationError(
            f"Notebook changed during inspection: {path}. Retry the request."
        )
    return NotebookSourceGeneration(expected_revision, *state_after)


def require_notebook_source_generation(
    path: Path,
    expected: NotebookSourceGeneration,
) -> None:
    """Reject a notebook whose content or file generation changed."""
    current = capture_notebook_source_generation(path, expected.revision)
    if current != expected:
        raise ConfigurationError(
            f"Notebook changed during inspection: {path}. Retry the request."
        )


def _state(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
