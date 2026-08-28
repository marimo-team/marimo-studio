from __future__ import annotations

import asyncio
import pydoc
import threading
from contextvars import ContextVar
from importlib.metadata import distribution
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import agent_plugins
import marimo._code_mode as code_mode
import pytest

import marimo_studio.agent as studio_agent
import marimo_studio.authoring as studio_authoring
from marimo_studio._browser_client.transport import StudioServerConnection
from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._validation.evidence import (
    BrowserObservation,
    ValidationEvidence,
)
from marimo_studio._validation.progressive import ValidationRequest
from marimo_studio._validation.results import CheckResult
from marimo_studio.agent import ShowResult
from marimo_studio.errors import (
    CapabilityInputError,
    ConfigurationError,
    ProtocolError,
    SourceConflictError,
    SourceValidationError,
)

from ..helpers import ready_runtime_status


def _workspace(notebook: Path) -> studio_authoring.Workspace:
    return studio_authoring.open_workspace(notebook)


def test_marimo_code_mode_loads_the_studio_workspace_api() -> None:
    assert code_mode.capabilities()["studio"] == "marimo_studio.agent"
    entry_points = [
        item
        for item in distribution("marimo-studio").entry_points
        if item.group == "marimo.agent.capability"
    ]

    assert [(item.name, item.value) for item in entry_points] == [
        ("studio", "marimo_studio.agent")
    ]
    assert entry_points[0].load() is studio_agent
    assert set(studio_agent.__all__) == {
        "ValidationIssue",
        "ValidationReport",
        "View",
        "ShowResult",
        "Workspace",
        "agent_plugin",
        "agent_skill",
        "current_workspace",
    }


def test_agent_plugin_exposes_the_packaged_studio_skill() -> None:
    plugin = studio_agent.agent_plugin()
    skill = studio_agent.agent_skill()

    assert plugin.manifest.name == "marimo-studio"
    assert skill in plugin.skills
    assert skill.path.name == "marimo-studio"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "agents" / "openai.yaml").is_file()
    assert skill.frontmatter.splitlines()[0] == "name: marimo-studio"
    assert isinstance(skill, agent_plugins.Skill)


def test_agent_module_help_points_to_the_packaged_studio_skill() -> None:
    plugin = studio_agent.agent_plugin()
    skill = studio_agent.agent_skill()
    rendered = pydoc.render_doc(studio_agent)

    assert str(plugin.path) in rendered
    assert str(skill / "SKILL.md") in rendered
    assert "resources = studio_agent.agent_plugin()" in rendered
    assert "skill = studio_agent.agent_skill()" in rendered


def test_agent_creation_and_binding_share_the_saved_notebook(
    notebook_path: Path,
) -> None:
    workspace = _workspace(notebook_path)

    async def exercise():
        starter = next(
            starter
            for starter in await workspace.starters()
            if starter.id == "marimo-studio/vanilla:default"
        )
        view = await workspace.create_view("dashboard", starter=starter)
        notebook = await workspace.inspect_notebook()
        binding = await workspace.bind("summary", notebook.cells[1].ref)
        return view, binding

    view, binding = asyncio.run(exercise())

    assert workspace.notebook == notebook_path.resolve()
    assert view.workspace is workspace
    assert view.name == "dashboard"
    assert binding.alias == "summary"


def test_workspace_sync_operations_preserve_context_from_an_active_loop(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(notebook_path)
    request_context = ContextVar("agent-request-context", default="missing")
    request_context.set("code-mode")
    caller_thread = threading.get_ident()
    observations: list[tuple[int, str]] = []

    def overview(notebook: Path):
        observations.append((threading.get_ident(), request_context.get()))
        return SimpleNamespace(notebook=notebook)

    monkeypatch.setattr("marimo_studio._authoring.workspace.overview", overview)

    async def exercise():
        return await workspace.status()

    result = asyncio.run(exercise())

    assert result.notebook == notebook_path.resolve()
    assert observations == [(observations[0][0], "code-mode")]
    assert observations[0][0] != caller_thread


def test_view_inspection_matches_its_json_shape(notebook_path: Path) -> None:
    workspace = _workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))

    result = asyncio.run(view.inspect())
    payload = result.to_dict()

    assert result.view == payload["view"] == "dashboard"
    assert result.freshness == payload["freshness"] == "unbuilt"
    assert all(item.access == "edit" for item in result.documents)
    assert [item.path.as_posix() for item in result.documents] == [
        "view.toml",
        "index.html",
        "AGENTS.md",
    ]
    assert result.build is None


def test_view_documents_use_revision_aware_source_operations(
    notebook_path: Path,
) -> None:
    workspace = _workspace(notebook_path)

    async def exercise() -> None:
        view = await workspace.create_view("dashboard")
        document = await view.read("index.html")
        updated = await view.write(
            "index.html",
            document.content.replace("Dashboard", "Agent dashboard"),
            expected_revision=document.revision,
        )
        assert updated.revision != document.revision
        assert "Agent dashboard" in updated.content
        with pytest.raises(SourceConflictError):
            await view.write(
                "index.html",
                document.content,
                expected_revision=document.revision,
            )

    asyncio.run(exercise())


def test_agent_repairs_a_malformed_view_manifest(notebook_path: Path) -> None:
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    manifest = (
        notebook_path.parent
        / "__marimo__"
        / "studio"
        / notebook_path.stem
        / "dashboard"
        / "view.toml"
    )
    valid = manifest.read_text(encoding="utf-8")
    del workspace
    manifest.write_bytes(b"schema = [\n")
    fresh_workspace = studio_authoring.open_workspace(notebook_path)
    recovered = fresh_workspace.view("dashboard")

    async def exercise() -> None:
        broken = await recovered.read("view.toml")
        assert broken.content == "schema = [\n"
        with pytest.raises(SourceValidationError):
            await recovered.write(
                "view.toml",
                "provider = [\n",
                expected_revision=broken.revision,
            )
        with pytest.raises(SourceConflictError):
            await recovered.write(
                "view.toml",
                valid,
                expected_revision="sha256:stale",
            )
        repaired = await recovered.write(
            "view.toml",
            valid,
            expected_revision=broken.revision,
        )
        assert repaired.content == valid
        assert (await recovered.inspect()).view == "dashboard"

    asyncio.run(exercise())


@pytest.mark.native_process
def test_validation_evidence_grows_by_level(notebook_path: Path) -> None:
    workspace = _workspace(notebook_path)

    async def exercise() -> None:
        await workspace.create_view("dashboard")
        static = await workspace.validate(level="static", view="dashboard")
        runtime = await workspace.validate(level="runtime", view="dashboard")
        assert set(static.evidence) == {"static"}
        assert set(runtime.evidence) == {"static", "runtime"}
        assert static.ok
        assert runtime.ok
        assert static.issues == ()
        assert runtime.issues == ()

    asyncio.run(exercise())


@pytest.mark.native_process
def test_workspace_runtime_inspection_returns_selected_outputs(
    notebook_path: Path,
) -> None:
    workspace = _workspace(notebook_path)

    result = asyncio.run(
        workspace.inspect_notebook(
            runtime=True,
            selectors=(1,),
        )
    )

    assert [cell.index for cell in result.cells] == [1]
    assert result.runtime is not None
    assert result.runtime.cells[result.cells[0].runtime_id].status == "idle"


def test_view_remove_returns_the_remaining_workspace(notebook_path: Path) -> None:
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    view = asyncio.run(workspace.create_view("report"))

    result = asyncio.run(view.remove())

    assert result.view == "report"
    assert result.views == ("dashboard",)


def test_authoring_doctor_returns_provider_diagnostics() -> None:
    report = asyncio.run(studio_authoring.doctor())

    assert report.providers
    assert report.to_dict()["schema"] == 1


def test_view_inspection_propagates_notebook_resolution_errors(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))

    def fail_resolution(*_args, **_kwargs):
        raise ConfigurationError("Notebook graph is invalid")

    monkeypatch.setattr("marimo_studio._views.resolve.resolve_studio", fail_resolution)

    with pytest.raises(ConfigurationError, match="Notebook graph is invalid"):
        asyncio.run(view.inspect())


def test_view_build_cancellation_closes_a_late_lease(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class Lease:
        def close(self) -> None:
            closed.set()

    def build(*_args, **_kwargs):
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert release.wait(timeout=2)
            return Lease()
        finally:
            unregister()

    monkeypatch.setattr("marimo_studio._views.build.publish_view", build)

    async def exercise() -> None:
        task = asyncio.create_task(view.build())
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        assert await asyncio.to_thread(cancelled.wait, 1)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())

    assert closed.is_set()


def test_view_write_cancellation_drains_atomic_commit_before_return(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import marimo_studio._authoring.view as view_operations
    import marimo_studio._views.sources as sources_module

    workspace = _workspace(notebook_path)
    view = asyncio.run(workspace.create_view("dashboard"))
    loaded = asyncio.run(view.read("index.html"))
    updated = loaded.content + "\n"
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()
    write_source = sources_module.write_source

    def write(*args: Any, **kwargs: Any):
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert release.wait(timeout=2)
            return write_source(*args, **kwargs)
        finally:
            unregister()

    monkeypatch.setattr(view_operations, "write_source", write)

    async def exercise() -> None:
        mutation = asyncio.create_task(
            view.write(
                "index.html",
                updated,
                expected_revision=loaded.revision,
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        mutation.cancel()
        assert await asyncio.to_thread(cancelled.wait, 1)
        mutation.cancel()
        assert not mutation.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await mutation
        assert mutation.done()
        assert mutation.cancelled()
        path = notebook_path.parent.joinpath(
            "__marimo__",
            "studio",
            notebook_path.stem,
            "dashboard",
            "index.html",
        )
        assert path.read_text(encoding="utf-8") == updated

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_workspace_bind_cancellation_drains_atomic_commit_before_return(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import marimo_studio._authoring.workspace as workspace_operations
    import marimo_studio._views.api as views_api
    from marimo_studio._workspace import load_studio

    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()
    bind_cell = views_api.bind_cell

    def bind(*args: Any, **kwargs: Any):
        control = current_provider_cancellation()
        assert control is not None
        unregister = control.register(cancelled.set)
        started.set()
        try:
            assert release.wait(timeout=2)
            return bind_cell(*args, **kwargs)
        finally:
            unregister()

    monkeypatch.setattr(workspace_operations, "bind_cell_operation", bind)

    async def exercise() -> None:
        mutation = asyncio.create_task(workspace.bind("late-binding", 0))
        assert await asyncio.to_thread(started.wait, 1)
        mutation.cancel()
        assert await asyncio.to_thread(cancelled.wait, 1)
        mutation.cancel()
        assert not mutation.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await mutation
        assert mutation.done()
        assert mutation.cancelled()
        assert "late-binding" in load_studio(notebook_path).cells

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_current_workspace_uses_the_notebook_attached_to_code_mode(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: StudioServerConnection("http://localhost:2718"),
        ),
    )

    current = studio_agent.current_workspace()
    saved = studio_authoring.open_workspace(notebook_path)

    assert current.notebook == saved.notebook == notebook_path.resolve()
    assert isinstance(current, studio_agent.Workspace)
    assert isinstance(current.view("dashboard"), studio_agent.View)
    assert isinstance(saved, studio_authoring.Workspace)
    assert isinstance(saved.view("dashboard"), studio_authoring.View)
    with pytest.raises(TypeError, match=r"authoring\.open_workspace"):
        cast(Any, studio_agent.Workspace)(notebook_path)
    with pytest.raises(TypeError, match="authoring workspace"):
        cast(Any, studio_agent.View)(object(), "dashboard")
    with pytest.raises(ConfigurationError, match="Notebook does not exist"):
        studio_authoring.open_workspace(notebook_path.with_name("missing.py"))


def test_workspace_validates_notebook_and_binding_inputs(notebook_path: Path) -> None:
    workspace = _workspace(notebook_path)
    asyncio.run(workspace.create_view("dashboard"))

    with pytest.raises(CapabilityInputError, match="greater than or equal to 1"):
        asyncio.run(workspace.inspect_notebook(limit=0))
    for selector in (-1, True):
        with pytest.raises(CapabilityInputError, match="Unknown cell selector"):
            asyncio.run(workspace.bind("summary", cast(Any, selector)))


def test_view_analysis_uses_the_attached_studio_server(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_workspace(notebook_path).create_view("dashboard"))
    connection = StudioServerConnection(
        "http://localhost:2718",
        session_id="s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: connection,
        ),
    )
    workspace = studio_agent.current_workspace()
    view = workspace.view("dashboard")

    async def analyze(_connection, notebook, request):
        assert request == ValidationRequest(view="dashboard")
        return ValidationEvidence(
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
                    runtime_status=ready_runtime_status("dashboard", "revision-1"),
                ),
            ),
            browser_required=True,
            issues=(),
        )

    monkeypatch.setattr(
        "marimo_studio._authoring.validation.request_browser_validation", analyze
    )

    report = asyncio.run(view.validate(level="browser"))

    assert report.level == "browser"
    assert report.ok is True
    assert report.evidence["browser"]


def test_view_analysis_requires_the_attached_server(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_workspace(notebook_path).create_view("dashboard"))

    def unavailable() -> StudioServerConnection:
        raise ProtocolError("Studio metadata is unavailable.")

    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=unavailable,
        ),
    )
    view = studio_agent.current_workspace().view("dashboard")

    with pytest.raises(ProtocolError, match="Studio metadata is unavailable"):
        asyncio.run(view.validate(level="browser"))


def test_view_show_targets_the_attached_browser(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_workspace(notebook_path).create_view("dashboard"))
    connection = StudioServerConnection(
        "http://localhost:2718",
        session_id="s_123456",
    )
    monkeypatch.setattr(
        "marimo_studio._composition.create_code_mode_bridge",
        lambda: SimpleNamespace(
            active_notebook=lambda: notebook_path.resolve(),
            connection=lambda: connection,
        ),
    )
    view = studio_agent.current_workspace().view("dashboard")

    async def show(studio, _connection, name):
        return ShowResult(
            notebook=studio.notebook,
            view=name,
            generation=2,
            client_id="browser-client-1234",
            session_id="s_123456",
        )

    monkeypatch.setattr(
        "marimo_studio._authoring.view.show_browser_view",
        show,
    )

    result = asyncio.run(view.show())

    assert result.view == "dashboard"
    assert result.generation == 2
