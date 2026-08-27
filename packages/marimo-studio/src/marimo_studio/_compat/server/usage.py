"""Keep native usage polling stable while a process sample is unavailable."""

from __future__ import annotations

from psutil import AccessDenied, NoSuchProcess
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._compat.patch import CallbackCloseHandle, ReversiblePatch
from marimo_studio.errors._internal import CompatibilityError


def _unavailable_usage_snapshot() -> dict[str, object]:
    return {
        "memory": {
            "total": None,
            "available": None,
            "percent": None,
            "used": None,
            "free": None,
            "has_cgroup_mem_limit": False,
        },
        "server": {"memory": None},
        "kernel": {"memory": None},
        "cpu": {"percent": None},
        "gpu": [],
    }


def _wrap_usage_app(native: ASGIApp) -> ASGIApp:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await native(scope, receive, tracked_send)
        except (AccessDenied, NoSuchProcess):
            if response_started:
                raise
            await JSONResponse(
                _unavailable_usage_snapshot(),
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)

    return app


def _usage_route() -> Route:
    from marimo._server.api.endpoints import health

    matches = [
        route
        for route in health.router.routes
        if isinstance(route, Route) and route.path == "/api/usage"
    ]
    if len(matches) != 1:
        raise CompatibilityError("The pinned Marimo usage route is unavailable.")
    route = matches[0]
    captured = tuple(
        cell.cell_contents
        for cell in (getattr(route.endpoint, "__closure__", None) or ())
    )
    if route.methods != {"GET", "HEAD"} or not any(
        value is health.usage for value in captured
    ):
        raise CompatibilityError("The pinned Marimo usage route identity changed.")
    return route


_USAGE_PATCH = ReversiblePatch(
    "usage process sampling",
    _usage_route(),
    "app",
    _wrap_usage_app,
)


class PrivateUsageRoute:
    """Install the usage sampling adapter for one lifespan."""

    def open(self) -> CallbackCloseHandle:
        return _USAGE_PATCH.open()
