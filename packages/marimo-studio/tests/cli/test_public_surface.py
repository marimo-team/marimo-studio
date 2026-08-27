from __future__ import annotations

import ast
from pathlib import Path

import click

import marimo_studio.agent as studio_agent
from marimo_studio._cli import cli


def test_cli_exposes_the_resource_first_authoring_contract() -> None:
    assert set(cli.commands) == {
        "doctor",
        "notebook",
        "starters",
        "status",
        "validate",
        "view",
    }
    notebook = cli.commands["notebook"]
    view = cli.commands["view"]
    assert isinstance(notebook, click.Group)
    assert isinstance(view, click.Group)
    assert set(notebook.commands) == {"bind", "inspect"}
    assert set(view.commands) == {
        "activate",
        "build",
        "create",
        "export",
        "inspect",
        "read",
        "remove",
        "write",
    }


def test_agent_handles_expose_the_same_authoring_capabilities() -> None:
    assert {
        "bind",
        "create_view",
        "inspect_notebook",
        "starters",
        "status",
        "validate",
        "view",
    }.issubset(vars(studio_agent.Workspace))
    assert {
        "activate",
        "build",
        "export",
        "inspect",
        "read",
        "remove",
        "validate",
        "write",
    }.issubset(vars(studio_agent.View))
    assert callable(studio_agent.doctor)


def test_agent_entrypoint_contains_imports_and_exports() -> None:
    path = Path(studio_agent.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = tuple(
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    assert definitions == ()


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
