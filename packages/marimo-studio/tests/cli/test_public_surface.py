from __future__ import annotations

from pathlib import Path

import click

import marimo_studio.agent as studio_agent
import marimo_studio.authoring as studio_authoring
from marimo_studio._cli import cli

PARITY = (
    (studio_authoring, "doctor", ("doctor",)),
    (studio_authoring.Workspace, "status", ("status",)),
    (studio_authoring.Workspace, "inspect_notebook", ("notebook", "inspect")),
    (studio_authoring.Workspace, "bind", ("notebook", "bind")),
    (studio_authoring.Workspace, "starters", ("starters",)),
    (studio_authoring.Workspace, "create_view", ("view", "create")),
    (studio_authoring.Workspace, "validate", ("validate",)),
    (studio_authoring.View, "inspect", ("view", "inspect")),
    (studio_authoring.View, "read", ("view", "read")),
    (studio_authoring.View, "write", ("view", "write")),
    (studio_authoring.View, "build", ("view", "build")),
    (studio_agent.View, "show", ("view", "show")),
    (studio_authoring.View, "validate", ("validate",)),
    (studio_authoring.View, "export", ("view", "export")),
    (studio_authoring.View, "remove", ("view", "remove")),
)


def _leaf_paths(
    group: click.Group, prefix: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for name, command in group.commands.items():
        path = (*prefix, name)
        if isinstance(command, click.Group):
            paths.update(_leaf_paths(command, path))
        else:
            paths.add(path)
    return paths


def test_python_and_cli_authoring_operations_stay_in_parity() -> None:
    for owner, member, _path in PARITY:
        assert callable(getattr(owner, member))
    assert _leaf_paths(cli) == {path for _owner, _member, path in PARITY}


def test_browser_operations_belong_to_the_live_agent_view() -> None:
    assert studio_agent.View is not studio_authoring.View
    assert studio_agent.Workspace is not studio_authoring.Workspace
    assert not hasattr(studio_authoring.View, "show")
    assert hasattr(studio_agent.View, "show")


def test_cli_commands_depend_on_authoring_services() -> None:
    commands = Path(__file__).parents[2] / "src" / "marimo_studio" / "_cli" / "commands"
    for path in commands.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "marimo_studio.agent" not in source
    service_users = {
        path.name
        for path in commands.glob("*.py")
        if "marimo_studio._authoring" in path.read_text(encoding="utf-8")
    }
    assert service_users == {
        "doctor.py",
        "notebook.py",
        "starters.py",
        "status.py",
        "validate.py",
        "view_create.py",
        "view_delivery.py",
        "view_source.py",
    }
