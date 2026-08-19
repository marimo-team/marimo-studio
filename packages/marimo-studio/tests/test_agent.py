from __future__ import annotations

import asyncio
import pydoc
from importlib.metadata import distribution
from types import SimpleNamespace
from typing import cast, get_type_hints

import marimo._code_mode as code_mode
import pytest

import marimo_studio.agent as studio_agent
from marimo_studio._agent_client import StudioServerConnection
from marimo_studio.agent_models import (
    AnalysisReport,
    BrowserObservation,
    ViewActivationResult,
)
from marimo_studio.analysis import AnalysisRequest
from marimo_studio.errors import CapabilityInputError, ProtocolError
from marimo_studio.types import CheckResult

from .helpers import ready_runtime_status


def test_marimo_code_mode_discovers_the_studio_capability() -> None:
    assert code_mode.capabilities()["studio"] == "marimo_studio.agent"


def test_agent_capability_entry_point_loads_the_instruction_module() -> None:
    capabilities = [
        entry_point
        for entry_point in distribution("marimo-studio").entry_points
        if entry_point.group == "marimo.agent.capability"
    ]

    assert [(entry.name, entry.value) for entry in capabilities] == [
        ("studio", "marimo_studio.agent")
    ]
    assert capabilities[0].load() is studio_agent


def test_agent_plugin_exposes_the_packaged_studio_skill() -> None:
    plugin = studio_agent.agent_plugin()
    skill = studio_agent.agent_skill()

    assert plugin.manifest.name == "marimo-studio"
    assert skill in plugin.skills
    assert skill.path.name == "marimo-studio"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "agents" / "openai.yaml").is_file()
    assert skill.frontmatter.splitlines()[0] == "name: marimo-studio"


def test_agent_module_help_points_to_installed_resources() -> None:
    plugin = studio_agent.agent_plugin()
    skill = studio_agent.agent_skill()
    rendered = pydoc.render_doc(studio_agent)

    assert str(plugin.path) in rendered
    assert str(skill / "SKILL.md") in rendered
    assert "resources = studio.agent_plugin()" in rendered
    assert "skill = studio.agent_skill()" in rendered


def test_public_agent_annotations_resolve_at_runtime() -> None:
    for name in studio_agent.__all__:
        assert get_type_hints(getattr(studio_agent, name))


def test_agent_operations_target_the_active_notebook(notebook_path) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})

    setup = studio_agent.ensure_view(context, "dashboard")
    inventory = studio_agent.inspect(context, include_code=True)
    binding = studio_agent.bind(context, "summary", 1)
    results = studio_agent.check(context, view_name="dashboard")

    assert setup.notebook == notebook_path.resolve()
    assert inventory.notebook.path == notebook_path.resolve()
    assert all(cell.code is not None for cell in inventory.cells)
    assert binding.alias == "summary"
    assert results.ok is True


def test_agent_operations_require_a_saved_notebook() -> None:
    context = SimpleNamespace(globals={})

    with pytest.raises(RuntimeError, match="Save the active notebook"):
        studio_agent.notebook_path(context)


def test_agent_inspection_validates_the_shared_limit(notebook_path) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})

    with pytest.raises(CapabilityInputError, match="greater than or equal to 1"):
        studio_agent.inspect(context, limit=0)


@pytest.mark.parametrize("cell_index", [-1, True])
def test_agent_binding_validates_the_shared_cell_index(
    notebook_path,
    cell_index: object,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agent.ensure_view(context, "dashboard")

    with pytest.raises(CapabilityInputError, match="nonnegative integer"):
        studio_agent.bind(context, "summary", cast(int, cell_index))


def test_agent_analysis_runs_through_the_attached_studio_server(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agent.ensure_view(context, "dashboard")
    connection = StudioServerConnection("http://localhost:2718")
    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: connection)
        ),
    )

    async def analyze(_connection, notebook, request):
        assert request == AnalysisRequest(view="dashboard")
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
                    runtime_status=ready_runtime_status(
                        "dashboard",
                        "revision-1",
                    ),
                ),
            ),
            browser_required=True,
            actions=(),
        )

    monkeypatch.setattr(
        "marimo_studio._agent_client.request_analysis",
        analyze,
    )

    report = asyncio.run(studio_agent.analyze(context, view="dashboard"))

    assert report.handoff_ready is True
    assert report.browser_observations[0].state == "ready"


def test_agent_analysis_requires_the_attached_studio_server(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agent.ensure_view(context, "dashboard")

    def unavailable() -> StudioServerConnection:
        raise ProtocolError("Studio metadata is unavailable.")

    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(code_mode=SimpleNamespace(connection=unavailable)),
    )

    with pytest.raises(ProtocolError, match="Studio metadata is unavailable"):
        asyncio.run(studio_agent.analyze(context, view="dashboard"))


def test_agent_analysis_requires_a_focused_view_before_connecting(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agent.ensure_view(context, "dashboard")
    connected = False

    def connection() -> StudioServerConnection:
        nonlocal connected
        connected = True
        raise AssertionError("invalid input reached the connection boundary")

    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(code_mode=SimpleNamespace(connection=connection)),
    )

    with pytest.raises(CapabilityInputError) as raised:
        asyncio.run(studio_agent.analyze(context))

    assert raised.value.code == "focused-analysis-required"
    assert raised.value.field == "view"
    assert connected is False


def test_agent_analysis_validates_the_runtime_timeout(notebook_path) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agent.ensure_view(context, "dashboard")

    with pytest.raises(CapabilityInputError, match="runtime_timeout"):
        asyncio.run(
            studio_agent.analyze(
                context,
                view="dashboard",
                runtime_timeout=float("inf"),
            )
        )


def test_agent_can_request_the_active_studio_view(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agent.ensure_view(context, "dashboard")
    connection = StudioServerConnection("http://localhost:2718")
    monkeypatch.setattr(
        "marimo_studio._composition.create_tooling_adapters",
        lambda: SimpleNamespace(
            code_mode=SimpleNamespace(connection=lambda: connection)
        ),
    )

    async def activate(_connection, notebook, request):
        return ViewActivationResult(
            notebook=notebook,
            view=request.view,
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

    result = asyncio.run(studio_agent.activate_view(context, "dashboard"))

    assert result.view == "dashboard"
    assert result.state == "active"
    assert result.transition == "in-place"
