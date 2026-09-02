from __future__ import annotations

import argparse
from importlib.metadata import version

EXPECTED_MARIMO_VERSION = "0.24.0"
EXPECTED_DEFAULT_LSP_PORT = 2718


def configure_lsp_port(port_offset: int, marimo_version: str | None = None) -> int:
    installed_version = marimo_version or version("marimo")
    if installed_version != EXPECTED_MARIMO_VERSION:
        raise RuntimeError(
            "E2E Marimo launcher expected version "
            f"{EXPECTED_MARIMO_VERSION}, found {installed_version}"
        )
    if port_offset < 0:
        raise ValueError("E2E Marimo port offset must be non-negative")

    from marimo._server import start

    if start.DEFAULT_PORT != EXPECTED_DEFAULT_LSP_PORT:
        raise RuntimeError(
            "E2E Marimo launcher expected default LSP port "
            f"{EXPECTED_DEFAULT_LSP_PORT}, found {start.DEFAULT_PORT}"
        )
    lsp_port = EXPECTED_DEFAULT_LSP_PORT + port_offset
    if lsp_port > 65_535:
        raise ValueError("E2E Marimo LSP port must not exceed 65535")
    start.DEFAULT_PORT = lsp_port
    return lsp_port


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--port-offset", required=True, type=int)
    options, marimo_args = parser.parse_known_args()
    configure_lsp_port(options.port_offset)

    from marimo._cli.cli import main as marimo

    marimo(args=["edit", *marimo_args], prog_name="marimo")


if __name__ == "__main__":
    main()
