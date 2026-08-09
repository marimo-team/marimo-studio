from __future__ import annotations

from importlib.metadata import distribution
from types import SimpleNamespace

import pytest

import marimo_studio.agents as studio_agents


def test_agent_capability_discovers_its_instruction_module() -> None:
    capabilities = [
        entry_point
        for entry_point in distribution("marimo-studio").entry_points
        if entry_point.group == "marimo.agent.capability"
    ]

    assert [(entry.name, entry.value) for entry in capabilities] == [
        ("studio", "marimo_studio.agents")
    ]
    assert capabilities[0].load() is studio_agents


def test_agent_operations_target_the_active_notebook(notebook_path) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})

    setup = studio_agents.ensure_view(context, "dashboard")
    inventory = studio_agents.inspect(context, include_code=True)
    binding = studio_agents.bind(context, "summary", 1)
    results = studio_agents.check(context, view_name="dashboard")

    assert setup.notebook == notebook_path.resolve()
    assert inventory.path == notebook_path.resolve()
    assert all(cell.code is not None for cell in inventory.cells)
    assert binding.alias == "summary"
    assert not [result for result in results if result.status == "fail"]


def test_agent_operations_require_a_saved_notebook() -> None:
    context = SimpleNamespace(globals={})

    with pytest.raises(RuntimeError, match="Save the active notebook"):
        studio_agents.notebook_path(context)
