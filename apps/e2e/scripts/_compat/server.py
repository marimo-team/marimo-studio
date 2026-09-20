"""Run fixture servers on a child-owned ephemeral socket without rebinding."""

from __future__ import annotations

import os
import runpy
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

import uvicorn

publish_endpoint = runpy.run_path(str(Path(__file__).with_name("endpoint.py")))[
    "publish_endpoint"
]

EXPECTED_MARIMO_VERSION = "0.24.2"


def configure_editor_fixture() -> None:
    installed_version = version("marimo")
    if installed_version != EXPECTED_MARIMO_VERSION:
        raise RuntimeError(
            f"E2E Marimo launcher expected version {EXPECTED_MARIMO_VERSION}, "
            f"found {installed_version}"
        )
    if not os.environ.get("XDG_CONFIG_HOME"):
        raise RuntimeError("E2E Marimo requires an isolated XDG_CONFIG_HOME")
    from marimo._config.config import DEFAULT_CONFIG
    from marimo._server.lsp import CopilotLspServer

    if any(
        config.get("enabled", False)
        for config in DEFAULT_CONFIG.get("language_servers", {}).values()
    ):
        raise RuntimeError("E2E expects native language servers to default off")

    async def skip_external_completion(_self: CopilotLspServer) -> None:
        # Acceptance exercises persisted config and editor-extension mount/unmount.
        # External Copilot completion transport is outside that witness; the real
        # config API and frontend extension still run unchanged.
        return None

    CopilotLspServer.start = skip_external_completion


@contextmanager
def bound_http_server() -> Iterator[int]:
    original_run = uvicorn.Server.run
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]

        def run(
            server: uvicorn.Server, sockets: list[socket.socket] | None = None
        ) -> None:
            if sockets is not None:
                raise RuntimeError("E2E server already received listening sockets")
            server.config.host = "127.0.0.1"
            server.config.port = port
            publish_endpoint(port)
            original_run(server, sockets=[listener])

        uvicorn.Server.run = run
        try:
            yield port
        finally:
            uvicorn.Server.run = original_run


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in {"marimo", "python"} or len(args) < 2:
        raise SystemExit("Expected marimo edit|run|new ... or python <script> ...")
    configure_editor_fixture()
    with bound_http_server() as port:
        if args[0] == "marimo":
            if args[1] not in {"edit", "run", "new"}:
                raise SystemExit("Expected marimo edit, run, or new")
            from marimo._cli.cli import main as marimo

            marimo(
                args=[*args[1:], "--host", "127.0.0.1", "--port", str(port)],
                prog_name="marimo",
            )
        else:
            sys.argv = args[1:]
            if not getattr(sys.flags, "safe_path", False):
                sys.path.insert(0, str(Path(args[1]).resolve().parent))
            runpy.run_path(args[1], run_name="__main__")


if __name__ == "__main__":
    main()
