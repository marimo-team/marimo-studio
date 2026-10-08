"""Adapt a Marimo notebook for the browser runtime."""

from __future__ import annotations

import ast
import inspect
import textwrap
from importlib.metadata import packages_distributions
from pathlib import Path

import marimo_export.values
from packaging.utils import NormalizedName, canonicalize_name

from marimo_studio._compat.browser_bridge import install_browser_bridge
from marimo_studio._compat.kernel_values.arrow import (
    _ArrowMaterializationRequired,
    _ArrowValueTooLarge,
    _dataframe_ipc,
)
from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio._compat.notebook import run_guard_line
from marimo_studio._delivery.urls import PRIVATE_QUERY_KEYS
from marimo_studio._projections import media_output
from marimo_studio._projections.resolution import (
    MAX_UNIQUE_OUTPUT_TARGETS,
    MAX_UNIQUE_VALUE_TARGETS,
)
from marimo_studio._projections.runtime_records import (
    BROWSER_VALUE_LIMITS,
    MAX_OUTPUT_BYTES,
    MEDIA_SCALE,
)
from marimo_studio._workspace.metadata import browser_notebook_metadata_source

MAX_ERROR_MESSAGE_LENGTH = 1_024
WASM_PROJECTION_NAMESPACE = "_marimo_studio_wasm"
BROWSER_BRIDGE_CELL_NAME = "__marimo_studio_values"


def _imported_distributions(source: str) -> frozenset[NormalizedName]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset()
    modules = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    modules.update(
        node.module.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    )
    distributions = packages_distributions()
    imported = {canonicalize_name(module) for module in modules}
    imported.update(
        canonicalize_name(distribution)
        for module in modules
        for distribution in distributions.get(module, ())
    )
    return frozenset(imported)


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
    implementation = textwrap.indent(
        "\n\n".join(
            (
                inspect.getsource(_ArrowMaterializationRequired),
                inspect.getsource(_ArrowValueTooLarge),
                inspect.getsource(_dataframe_ipc),
                _bridge_body(),
            )
        ),
        "    ",
    )
    private_query_keys = tuple(sorted(PRIVATE_QUERY_KEYS))
    return f"""@app.cell(hide_code=True)
def {BROWSER_BRIDGE_CELL_NAME}():
    _studio_config_private_query_keys = frozenset({private_query_keys!r})
    _studio_config_output_owner_prefix = {OUTPUT_OWNER_PREFIX!r}
    _studio_config_namespace = {WASM_PROJECTION_NAMESPACE!r}
    _studio_config_max_value_selector_count = {MAX_UNIQUE_VALUE_TARGETS}
    _studio_config_max_json_value_bytes = {BROWSER_VALUE_LIMITS.json_value_bytes}
    _studio_config_max_json_read_bytes = {BROWSER_VALUE_LIMITS.json_read_bytes}
    _studio_config_max_arrow_value_bytes = {BROWSER_VALUE_LIMITS.arrow_value_bytes}
    _studio_config_max_arrow_read_bytes = {BROWSER_VALUE_LIMITS.arrow_read_bytes}
    _studio_config_max_output_bytes = {MAX_OUTPUT_BYTES}
    _studio_config_max_error_message_length = {MAX_ERROR_MESSAGE_LENGTH}
    _studio_config_max_output_selectors = {MAX_UNIQUE_OUTPUT_TARGETS}
    _studio_config_media_scale = {MEDIA_SCALE!r}
    _studio_config_values_source = {inspect.getsource(marimo_export.values)!r}
    _studio_config_media_source = {inspect.getsource(media_output)!r}

{implementation}
"""


def browser_notebook_source(
    path: Path,
    source: str,
) -> str:
    """Return source for a full Pyodide notebook runtime."""
    sanitized = browser_notebook_metadata_source(
        path,
        source,
        imported_distributions=_imported_distributions(source),
    )
    bridge = _value_bridge()
    guard = run_guard_line(sanitized)
    if guard is None:
        separator = "" if not sanitized or sanitized.endswith("\n") else "\n"
        return sanitized + separator + "\n" + bridge
    lines = sanitized.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[: guard - 1])
    return sanitized[:offset] + bridge + sanitized[offset:]
