"""Adapt a Marimo notebook for the browser runtime."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from marimo_studio._compat.browser_bridge import install_browser_bridge
from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio._compat.notebook import run_guard_line
from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS
from marimo_studio._projections.records import ValueReference
from marimo_studio._projections.values import MAX_OUTPUT_SELECTORS, MAX_VALUE_PATH_STEPS
from marimo_studio._workspace.metadata import (
    _document,
    _replace_metadata,
    set_package_requirement,
)

MAX_VALUE_SELECTOR_COUNT = 100
MAX_VALUE_BYTES = 1_000_000
MAX_ERROR_MESSAGE_LENGTH = 1_024
WASM_PROJECTION_NAMESPACE = "_marimo_studio_wasm"
BROWSER_BRIDGE_CELL_NAME = "__marimo_studio_values"


def _sanitized_metadata(source: str, path: Path) -> str:
    document = _document(source, path)
    if document is None:
        return source
    set_package_requirement(document, None)
    tool = document.get("tool")
    if isinstance(tool, MutableMapping):
        tool.pop("marimo-studio", None)
        tool.pop("uv", None)
        if not tool:
            document.pop("tool", None)
    return _replace_metadata(source, path, document)


def selector_specs(
    references: Mapping[str, ValueReference],
) -> dict[str, tuple[str, tuple[tuple[str, str | int], ...]]]:
    return {
        source: (
            reference.variable,
            tuple((step.kind, step.value) for step in reference.path),
        )
        for source, reference in sorted(references.items())
    }


def _bridge_body() -> str:
    source = inspect.getsource(install_browser_bridge)
    module = ast.parse(source)
    function = module.body[0]
    if not isinstance(function, ast.FunctionDef):
        raise RuntimeError(
            "Browser bridge source must define one installation function"
        )
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        raise RuntimeError("Browser bridge installation function is empty")
    lines = source.splitlines(keepends=True)
    return textwrap.dedent("".join(lines[body[0].lineno - 1 : function.end_lineno]))


def _value_bridge() -> str:
    implementation = textwrap.indent(_bridge_body(), "    ")
    private_query_keys = tuple(sorted(PRIVATE_QUERY_KEYS))
    return f"""@app.cell(hide_code=True)
def {BROWSER_BRIDGE_CELL_NAME}():
    _studio_config_private_query_keys = frozenset({private_query_keys!r})
    _studio_config_output_owner_prefix = {OUTPUT_OWNER_PREFIX!r}
    _studio_config_namespace = {WASM_PROJECTION_NAMESPACE!r}
    _studio_config_max_value_selector_count = {MAX_VALUE_SELECTOR_COUNT}
    _studio_config_max_value_bytes = {MAX_VALUE_BYTES}
    _studio_config_max_error_message_length = {MAX_ERROR_MESSAGE_LENGTH}
    _studio_config_max_value_path_steps = {MAX_VALUE_PATH_STEPS}
    _studio_config_max_output_selectors = {MAX_OUTPUT_SELECTORS}

{implementation}
"""


def browser_notebook_source(
    path: Path,
    source: str,
) -> str:
    """Return source for a full Pyodide notebook runtime."""
    sanitized = _sanitized_metadata(source, path)
    bridge = _value_bridge()
    guard = run_guard_line(sanitized)
    if guard is None:
        separator = "" if not sanitized or sanitized.endswith("\n") else "\n"
        return sanitized + separator + "\n" + bridge
    lines = sanitized.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[: guard - 1])
    return sanitized[:offset] + bridge + sanitized[offset:]
