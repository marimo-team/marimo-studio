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
from marimo_studio._workspace.installation import (
    STUDIO_DISTRIBUTION,
    local_studio_source,
)

_DENO_DISTRIBUTION = "deno"


def studio_runtime_requirement() -> str:
    """Return the requirement that installs the Studio running this process.

    A sandboxed kernel loads Studio's kernel lifespan from its own environment,
    so it must import the same Studio as the server, just as Marimo binds the
    kernel to the running Marimo. An editable checkout layers as `-e <path>`, a
    local wheel or directory by its file URL, and an index install by version.
    """
    source = local_studio_source()
    if source is None:
        return f"{STUDIO_DISTRIBUTION}=={distribution(STUDIO_DISTRIBUTION).version}"
    if source.editable:
        return f"-e {source.path}"
    return f"{STUDIO_DISTRIBUTION} @ {source.url}"


def studio_runtime_requirements() -> tuple[str, ...]:
    """Return the Studio and Deno a sandboxed process needs to match the server.

    Code mode authors views inside the kernel, so framework providers there
    build with the same pinned Deno that the server's Studio uses.
    """
    try:
        deno = distribution(_DENO_DISTRIBUTION)
    except PackageNotFoundError:
        return (studio_runtime_requirement(),)
    return (studio_runtime_requirement(), f"{_DENO_DISTRIBUTION}=={deno.version}")


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
