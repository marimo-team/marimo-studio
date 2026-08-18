from __future__ import annotations

import asyncio
import pydoc
from importlib.metadata import distribution
from types import SimpleNamespace
from typing import get_type_hints

import marimo._code_mode as code_mode
import pytest

import marimo_studio.agents as studio_agents
from marimo_studio._agent_client import StudioServerConnection
from marimo_studio.agent_models import (
    AnalysisReport,
    BrowserObservation,
    ViewActivationResult,
)
from marimo_studio.errors import ProtocolError
from marimo_studio.types import CheckResult


def test_marimo_code_mode_discovers_the_studio_capability() -> None:
    assert code_mode.capabilities()["studio"] == "marimo_studio.agents"


def test_agent_capability_entry_point_loads_the_instruction_module() -> None:
    capabilities = [
        entry_point
        for entry_point in distribution("marimo-studio").entry_points
        if entry_point.group == "marimo.agent.capability"
    ]

    assert [(entry.name, entry.value) for entry in capabilities] == [
        ("studio", "marimo_studio.agents")
    ]
    assert capabilities[0].load() is studio_agents


def test_agent_plugin_exposes_the_packaged_studio_skill() -> None:
    plugin = studio_agents.agent_plugin()
    skill = studio_agents.agent_skill()

    assert plugin.manifest.name == "marimo-studio"
    assert skill in plugin.skills
    assert skill.path.name == "marimo-studio"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "agents" / "openai.yaml").is_file()
    assert skill.frontmatter.splitlines()[0] == "name: marimo-studio"


def test_agent_module_help_points_to_installed_resources() -> None:
    plugin = studio_agents.agent_plugin()
    skill = studio_agents.agent_skill()
    rendered = pydoc.render_doc(studio_agents)

    assert str(plugin.path) in rendered
    assert str(skill / "SKILL.md") in rendered
    assert "resources = studio.agent_plugin()" in rendered
    assert "skill = studio.agent_skill()" in rendered


def test_public_agent_annotations_resolve_at_runtime() -> None:
    for name in studio_agents.__all__:
        assert get_type_hints(getattr(studio_agents, name))


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


def test_agent_analysis_runs_through_the_attached_studio_server(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")
    connection = StudioServerConnection("http://localhost:2718")
    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: connection)
        ),
    )

    async def analyze(_connection, notebook, **kwargs):
        assert kwargs == {
            "view_name": "dashboard",
            "timeout": 10.0,
            "runtime_timeout": 60.0,
            "require_browser": True,
        }
        return AnalysisReport(
            notebook=notebook,
            views=("dashboard",),
            runtime="server",
            revisions={"dashboard": "revision-1"},
            static_checks=(CheckResult("static", "pass", "Sources are valid"),),
            runtime_checks=(CheckResult("runtime", "pass", "Notebook run completed"),),
            runtime_skipped=None,
            browser_observations=(
                BrowserObservation(
                    view="dashboard",
                    runtime="server",
                    revision="revision-1",
                    state="ready",
                    client_id="browser-client-1234",
                    runtime_instance="runtime-instance",
                    session_id="s_123456",
                    request_id="request-1",
                    sequence=1,
                ),
            ),
            browser_required=True,
            actions=(),
        )

    monkeypatch.setattr(
        "marimo_studio._agent_client.request_analysis",
        analyze,
    )

    report = asyncio.run(studio_agents.analyze(context, view_name="dashboard"))

    assert report.handoff_ready is True
    assert report.browser_observations[0].state == "ready"


def test_agent_analysis_requires_the_attached_studio_server(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")

    def unavailable() -> StudioServerConnection:
        raise ProtocolError("Studio metadata is unavailable.")

    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(code_mode=SimpleNamespace(connection=unavailable)),
    )

    with pytest.raises(ProtocolError, match="Studio metadata is unavailable"):
        asyncio.run(studio_agents.analyze(context, view_name="dashboard"))


def test_agent_browser_analysis_requires_one_named_view(notebook_path) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")

    with pytest.raises(ValueError, match="requires view_name"):
        asyncio.run(studio_agents.analyze(context))


def test_agent_analysis_validates_the_runtime_timeout(notebook_path) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")

    with pytest.raises(ValueError, match="runtime_timeout"):
        asyncio.run(
            studio_agents.analyze(
                context,
                view_name="dashboard",
                runtime_timeout=float("inf"),
            )
        )


def test_agent_can_request_the_active_studio_view(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")
    connection = StudioServerConnection("http://localhost:2718")
    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: connection)
        ),
    )

    async def activate(_connection, notebook, view):
        return ViewActivationResult(
            notebook=notebook,
            view=view,
            state="active",
            generation=2,
            transition="in-place",
            client_id="browser-client-1234",
            session_id="s_123456",
        )

    monkeypatch.setattr(
        "marimo_studio._agent_client.request_view_activation",
        activate,
    )

    result = asyncio.run(studio_agents.activate_view(context, "dashboard"))

    assert result.view == "dashboard"
    assert result.state == "active"
    assert result.transition == "in-place"
