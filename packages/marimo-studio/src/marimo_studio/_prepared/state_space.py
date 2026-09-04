"""Read one view's marimo-export state space through Studio filesystem policy."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from marimo_export import StateSpace
from marimo_export.errors import SpecError
from marimo_export.wire import canonical_json_sha256

from marimo_studio._filesystem.io import read_file_snapshot
from marimo_studio.errors import ConfigurationError, PublicationError

STATE_SPACE_FILE = "states.yaml"


@dataclass(frozen=True, slots=True)
class StateSpaceSource:
    path: Path
    state_space: StateSpace | None
    digest: str

    def require_current(self) -> None:
        if load_state_space_source(self.path.parent).digest != self.digest:
            raise PublicationError(
                f"The prepared state space changed while it was used: {self.path}"
            )


def state_space_path(view_root: Path) -> Path:
    return view_root / STATE_SPACE_FILE


def load_state_space_source(view_root: Path) -> StateSpaceSource:
    path = state_space_path(view_root)
    try:
        content, _mode = read_file_snapshot(path, root=view_root)
    except FileNotFoundError:
        digest = canonical_json_sha256({"state_space": None})
        return StateSpaceSource(path, None, digest)
    except (ConfigurationError, OSError) as error:
        raise PublicationError(
            f"Could not read the prepared state space: {path}"
        ) from error
    try:
        state_space = StateSpace.from_yaml(content, source=str(path))
    except SpecError as error:
        raise PublicationError(str(error)) from error
    return StateSpaceSource(path, state_space, sha256(content).hexdigest())


__all__ = [
    "STATE_SPACE_FILE",
    "StateSpaceSource",
    "load_state_space_source",
    "state_space_path",
]
