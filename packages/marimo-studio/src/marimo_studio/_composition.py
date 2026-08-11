"""Construct process-specific Marimo adapters for the pinned release."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from marimo_studio import _assets
from marimo_studio._capabilities import (
    AdapterLifecycle,
    ASGIMiddlewareFactory,
    BrowserRuntimeProjector,
    CloseHandle,
    ExportAdapters,
    ServerAdapters,
    ToolingAdapters,
)
from marimo_studio._compat.layout import (
    MARIMO_RELEASE_COMMIT,
    MARIMO_VERSION,
    assert_pinned_release,
)
from marimo_studio._compat.patch import CompositeCloseHandle
from marimo_studio._server.cell_alias_policy import CellAliasSourcePolicy


class _PrivateAdapterLifecycle:
    def __init__(self, installers: Iterable[AdapterLifecycle]) -> None:
        self._installers = tuple(installers)

    def open(self) -> CloseHandle:
        handles: list[CloseHandle] = []
        try:
            for installer in self._installers:
                handles.append(installer.open())
        except BaseException:
            CompositeCloseHandle(handles).close()
            raise
        return CompositeCloseHandle(handles)


def create_browser_runtime_projector() -> BrowserRuntimeProjector:
    """Construct the browser projector for the pinned Marimo release."""
    validate_marimo_release()
    from marimo_studio._compat.browser_runtime import PrivateBrowserRuntimeProjector

    _assets.validate_runtime_marimo_release(
        version=MARIMO_VERSION,
        commit=MARIMO_RELEASE_COMMIT,
    )
    return PrivateBrowserRuntimeProjector(
        version=MARIMO_VERSION,
        commit=MARIMO_RELEASE_COMMIT,
    )


def create_server_adapters() -> ServerAdapters:
    """Construct Marimo adapters for one Studio server application."""
    validate_marimo_release()
    from marimo_studio._compat.code_mode_adapter import PrivateCodeModeBridge
    from marimo_studio._compat.kernel_values.host import PrivateKernelProjectionHost
    from marimo_studio._compat.server.existing_session import (
        PrivateExistingSessionAttachment,
    )
    from marimo_studio._compat.server.gateway import PrivateServerGateway
    from marimo_studio._compat.server.notebook_save import (
        PrivateNotebookSaveTransform,
    )
    from marimo_studio._compat.server.peer_state import PrivatePeerStateRelay
    from marimo_studio._compat.server.session_replay import PrivateSessionReplay
    from marimo_studio._compat.server.session_state import PrivateSessionState

    sessions = PrivateExistingSessionAttachment()
    replay = PrivateSessionReplay()
    persistence = PrivateNotebookSaveTransform(CellAliasSourcePolicy())
    peers = PrivatePeerStateRelay()
    return ServerAdapters(
        server=PrivateServerGateway(),
        session_state=PrivateSessionState(),
        sessions=sessions,
        replay=replay,
        persistence=persistence,
        projections=PrivateKernelProjectionHost(),
        peers=peers,
        browser=create_browser_runtime_projector(),
        code_mode=PrivateCodeModeBridge(),
        lifecycle=_PrivateAdapterLifecycle((sessions, replay, persistence, peers)),
    )


def create_tooling_adapters() -> ToolingAdapters:
    """Construct Marimo adapters for checks, inspection, and code mode."""
    validate_marimo_release()
    from marimo_studio._compat.code_mode_adapter import PrivateCodeModeBridge
    from marimo_studio._compat.environment import inline_environment_flags
    from marimo_studio._compat.notebook import load_static_notebook
    from marimo_studio._compat.runtime_probe import probe_runtime

    return ToolingAdapters(
        notebook=load_static_notebook,
        runner=probe_runtime,
        environment=inline_environment_flags,
        code_mode=PrivateCodeModeBridge(),
    )


def create_export_adapters() -> ExportAdapters:
    """Construct Marimo adapters for static browser export."""
    browser = create_browser_runtime_projector()
    from marimo_studio._compat.static_export import static_runtime_config

    return ExportAdapters(
        browser=browser,
        runtime_config=static_runtime_config,
    )


def programmatic_middleware(
    notebook: Path,
) -> ASGIMiddlewareFactory:
    """Construct the Marimo middleware for one programmatic notebook."""
    validate_marimo_release()
    from marimo_studio._compat.server.programmatic import programmatic_middleware

    return programmatic_middleware(notebook)


def _construct_kernel_lifespan(value: None) -> Any:
    from marimo_studio._compat.kernel_values.kernel import kernel_lifespan as construct

    return construct(value)


def kernel_lifespan(value: None) -> Any:
    """Construct the Marimo kernel integration for one kernel lifespan."""
    validate_marimo_release()
    return _construct_kernel_lifespan(value)


def validate_marimo_release() -> str:
    """Validate every private capability against the pinned release."""
    return assert_pinned_release()


__all__ = [
    "create_browser_runtime_projector",
    "create_export_adapters",
    "create_server_adapters",
    "create_tooling_adapters",
    "kernel_lifespan",
    "programmatic_middleware",
    "validate_marimo_release",
]
