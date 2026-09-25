"""Layer the running Studio into Marimo's sandboxed notebook processes."""

from __future__ import annotations

from dataclasses import replace
from importlib.metadata import PackageNotFoundError, distribution
from typing import Any

from marimo._environments.overlay import RuntimeOverlay
from marimo._session.app_host import pool
from marimo._session.managers import ipc

from marimo_studio._compat.patch import CompositeCloseHandle, ReversiblePatch
from marimo_studio._server.ports import CloseHandle
from marimo_studio._workspace.installation import invoking_studio

_DENO_DISTRIBUTION = "deno"


def studio_runtime_requirements() -> tuple[str, ...]:
    """Return the Studio and Deno a sandboxed process needs to match the server.

    A sandboxed kernel loads Studio's kernel lifespan from its own environment,
    so it imports the Studio the server runs, just as Marimo binds the kernel
    to the running Marimo. Code mode authors views inside the kernel, so
    framework providers there build with the server's pinned Deno. A Studio
    without installed metadata has nothing to layer.
    """
    studio = invoking_studio()
    if studio is None:
        return ()
    try:
        deno = distribution(_DENO_DISTRIBUTION)
    except PackageNotFoundError:
        return (studio.requirement,)
    return (studio.requirement, f"{_DENO_DISTRIBUTION}=={deno.version}")


def _layer_studio(native: Any) -> Any:
    requirements = studio_runtime_requirements()

    def runtime_overlay(*args: Any, **kwargs: Any) -> RuntimeOverlay:
        overlay = native(*args, **kwargs)
        return replace(overlay, command=(*overlay.command, *requirements))

    return runtime_overlay


_KERNEL_OVERLAY_PATCH = ReversiblePatch(
    "sandbox-studio-runtime",
    ipc,
    "runtime_overlay",
    _layer_studio,
)
_APP_HOST_OVERLAY_PATCH = ReversiblePatch(
    "sandbox-studio-runtime",
    pool,
    "runtime_overlay",
    _layer_studio,
)


class PrivateSandboxRuntime:
    """Layer Studio into sandboxed kernels and app hosts for one lifespan."""

    def open(self) -> CompositeCloseHandle:
        patches: list[CloseHandle] = []
        try:
            for patch in (_KERNEL_OVERLAY_PATCH, _APP_HOST_OVERLAY_PATCH):
                patches.append(patch.open())
        except BaseException as setup_error:
            try:
                CompositeCloseHandle(patches).close()
            except BaseException as cleanup_error:
                raise setup_error from cleanup_error
            raise
        return CompositeCloseHandle(patches)
