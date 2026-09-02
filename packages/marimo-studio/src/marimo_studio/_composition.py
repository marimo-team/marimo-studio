"""Assemble pinned Marimo integrations behind Studio-owned contracts.

This module is the construction point for server, kernel, browser,
code-mode, notebook-inspection, runtime-probe, and export adapters. The rest of
Studio asks for its own interfaces and records instead of importing private
Marimo APIs throughout the product.

Every factory validates the required Marimo release before exposing an
adapter, and the browser projector checks that packaged assets identify the
same release. Opening several lifecycle adapters is all-or-nothing: a partial
setup is closed before the original startup failure returns to its owner.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import marimo_studio._delivery.assets as _assets
from marimo_studio._browser_client.ports import CodeModeBridge
from marimo_studio._compat.layout import (
    MARIMO_RELEASE_COMMIT,
    MARIMO_VERSION,
    assert_pinned_release,
)
from marimo_studio._compat.patch import CompositeCloseHandle
from marimo_studio._delivery.browser_ports import BrowserRuntimeProjector
from marimo_studio._delivery.ports import ExportAdapters
from marimo_studio._notebook.ports import (
    EnvironmentFlagBuilder,
    LiveNotebookRunner,
    StaticNotebookLoader,
)
from marimo_studio._server.cell_alias_policy import CellAliasSourcePolicy
from marimo_studio._server.ports import (
    AdapterLifecycle,
    ASGIMiddlewareFactory,
    CloseHandle,
    ServerAdapters,
)
from marimo_studio._server.security import (
    ALLOWED_EMBED_ORIGINS_ENV,
    SecurityPolicy,
    parse_allowed_embed_origins,
)


class _PrivateAdapterLifecycle:
    def __init__(self, installers: Iterable[AdapterLifecycle]) -> None:
        self._installers = tuple(installers)

    def open(self) -> CloseHandle:
        handles: list[CloseHandle] = []
        try:
            for installer in self._installers:
                handles.append(installer.open())
        except BaseException as setup_error:
            try:
                CompositeCloseHandle(handles).close()
            except BaseException as cleanup_error:
                raise setup_error from cleanup_error
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


def marimo_release_identity() -> dict[str, str]:
    """Return the Marimo release required by every Studio adapter."""
    return {
        "version": MARIMO_VERSION,
        "commit": MARIMO_RELEASE_COMMIT,
    }


def create_server_adapters() -> ServerAdapters:
    """Construct Marimo adapters for one Studio server application."""
    validate_marimo_release()
    from marimo_studio._compat.kernel_values.authorization_key import (
        initialize_projection_authorization_key,
    )

    initialize_projection_authorization_key()
    from marimo_studio._compat.code_mode_adapter import PrivateCodeModeBridge
    from marimo_studio._compat.kernel_values.host import PrivateKernelProjectionHost
    from marimo_studio._compat.server.document_transaction import (
        PrivateDocumentTransactionEvidence,
    )
    from marimo_studio._compat.server.editor_runtime import (
        PrivateEditorRuntimeBootstrap,
    )
    from marimo_studio._compat.server.existing_session import (
        PrivateExistingSessionAttachment,
    )
    from marimo_studio._compat.server.gateway import PrivateServerGateway
    from marimo_studio._compat.server.notebook_save import (
        PrivateNotebookSaveTransform,
    )
    from marimo_studio._compat.server.peer_state import PrivatePeerCommandRelay
    from marimo_studio._compat.server.session_cache import (
        PrivateSessionCachePublication,
    )
    from marimo_studio._compat.server.session_replay import PrivateSessionReplay
    from marimo_studio._compat.server.session_state import PrivateSessionState
    from marimo_studio._compat.server.usage import PrivateUsageRoute

    sessions = PrivateExistingSessionAttachment()
    replay = PrivateSessionReplay()
    persistence = PrivateNotebookSaveTransform(CellAliasSourcePolicy())
    peer_commands = PrivatePeerCommandRelay()
    session_cache = PrivateSessionCachePublication()
    usage = PrivateUsageRoute()
    return ServerAdapters(
        server=PrivateServerGateway(),
        editor_runtime=PrivateEditorRuntimeBootstrap(),
        document_transactions=PrivateDocumentTransactionEvidence(),
        session_state=PrivateSessionState(),
        sessions=sessions,
        replay=replay,
        persistence=persistence,
        projections=PrivateKernelProjectionHost(),
        peer_commands=peer_commands,
        browser=create_browser_runtime_projector(),
        code_mode=PrivateCodeModeBridge(),
        lifecycle=_PrivateAdapterLifecycle(
            (
                sessions,
                replay,
                persistence,
                peer_commands,
                session_cache,
                usage,
            )
        ),
    )


def create_security_policy() -> SecurityPolicy:
    """Load the process security policy for one server composition."""
    return parse_allowed_embed_origins(os.environ.get(ALLOWED_EMBED_ORIGINS_ENV, ""))


def install_presentation_authorization() -> CloseHandle:
    """Install the process-wide Marimo presentation authorization adapter."""
    validate_marimo_release()
    from marimo_studio._compat.server.presentation_auth import (
        PrivatePresentationAuthorization,
    )

    return PrivatePresentationAuthorization().open()


def create_static_notebook_loader() -> StaticNotebookLoader:
    """Construct the saved-notebook loader for the pinned Marimo release."""
    validate_marimo_release()
    from marimo_studio._compat.notebook import load_static_notebook

    return load_static_notebook


def create_runtime_probe() -> LiveNotebookRunner:
    """Construct the isolated runtime probe for the pinned Marimo release."""
    validate_marimo_release()
    from marimo_studio._notebook.runtime_process import probe_runtime_isolated

    return probe_runtime_isolated


def create_worker_runtime_probe() -> LiveNotebookRunner:
    """Construct the Marimo probe used inside an owned runtime worker."""
    validate_marimo_release()
    from marimo_studio._compat.runtime_probe import probe_runtime_in_worker

    return probe_runtime_in_worker


def create_environment_flag_builder() -> EnvironmentFlagBuilder:
    """Construct notebook environment flags for the pinned Marimo release."""
    validate_marimo_release()
    from marimo_studio._compat.environment import inline_environment_flags

    return inline_environment_flags


def create_code_mode_bridge() -> CodeModeBridge:
    """Construct the bridge to the active Marimo code-mode request."""
    validate_marimo_release()
    from marimo_studio._compat.code_mode_adapter import PrivateCodeModeBridge

    return PrivateCodeModeBridge()


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
    security_policy: SecurityPolicy | None = None,
) -> ASGIMiddlewareFactory:
    """Construct the Marimo middleware for one programmatic notebook."""
    validate_marimo_release()
    from marimo_studio._compat.server.programmatic import programmatic_middleware

    return programmatic_middleware(
        notebook,
        create_server_adapters,
        security_policy if security_policy is not None else create_security_policy(),
    )


def own_programmatic_lifespans(app: Any) -> Any:
    """Bind mounted Marimo resources to the returned application lifespan."""
    validate_marimo_release()
    from marimo_studio._compat.server.programmatic import (
        own_programmatic_lifespans as own,
    )

    return own(app)


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
