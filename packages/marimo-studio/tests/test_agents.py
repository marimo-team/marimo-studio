from __future__ import annotations

import asyncio
from importlib.metadata import distribution
from types import SimpleNamespace

import pytest

import marimo_studio.agents as studio_agents
from marimo_studio._agent_client import StudioServerConnection
from marimo_studio.types import (
    AnalysisReport,
    BrowserObservation,
    CheckResult,
    ViewActivationResult,
)


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


def test_agent_analysis_runs_through_the_attached_studio_server(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")
    connection = StudioServerConnection("http://localhost:2718")
    monkeypatch.setattr(
        "marimo_studio._compat.code_mode.code_mode_connection",
        lambda: connection,
    )

    async def analyze(_connection, notebook, **kwargs):
        assert kwargs == {
            "view_name": "dashboard",
            "timeout": 10.0,
            "require_browser": True,
        }
        return AnalysisReport(
            notebook=notebook,
            views=("dashboard",),
            static_checks=(CheckResult("static", "pass", "Sources are valid"),),
            runtime_checks=(CheckResult("runtime", "pass", "Notebook run completed"),),
            runtime_skipped=None,
            browser_observations=(
                BrowserObservation(
                    view="dashboard",
                    runtime="server",
                    revision="revision-1",
                    state="ready",
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


def test_agent_analysis_reports_a_missing_live_browser(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")

    async def runtime(*_args, **_kwargs):
        return (CheckResult("runtime", "pass", "Notebook run completed"),)

    monkeypatch.setattr("marimo_studio.analysis.check_runtime_studio", runtime)

    report = asyncio.run(studio_agents.analyze(context, view_name="dashboard"))

    assert report.handoff_ready is False
    assert report.browser_observations[0].state == "not-observed"
    assert report.actions[-1].code == "browser-not-observed"


def test_agent_can_request_the_active_studio_view(
    notebook_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = SimpleNamespace(globals={"__file__": str(notebook_path)})
    studio_agents.ensure_view(context, "dashboard")
    connection = StudioServerConnection("http://localhost:2718")
    monkeypatch.setattr(
        "marimo_studio._compat.code_mode.code_mode_connection",
        lambda: connection,
    )

    async def activate(_connection, notebook, view):
        return ViewActivationResult(
            notebook=notebook,
            view=view,
            state="requested",
            generation=2,
            transition="in-place",
        )

    monkeypatch.setattr(
        "marimo_studio._agent_client.request_view_activation",
        activate,
    )

    result = asyncio.run(studio_agents.activate_view(context, "dashboard"))

    assert result.view == "dashboard"
    assert result.state == "requested"
    assert result.transition == "in-place"
