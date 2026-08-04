"""Adapt a Marimo notebook for the browser runtime."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path

from marimo_studio._compat.notebook import run_guard_line
from marimo_studio._urls import PRIVATE_QUERY_KEYS
from marimo_studio._workspace.metadata import (
    _document,
    _replace_metadata,
    set_package_requirement,
)
from marimo_studio.types import ValueReference

MAX_SELECTOR_COUNT = 100
MAX_SELECTOR_LENGTH = 512
MAX_VALUE_BYTES = 1_000_000
MAX_ERROR_MESSAGE_LENGTH = 1_024


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


def _selector_specs(
    references: Mapping[str, ValueReference],
) -> dict[str, tuple[str, tuple[tuple[str, str | int], ...]]]:
    return {
        source: (
            reference.variable,
            tuple((step.kind, step.value) for step in reference.path),
        )
        for source, reference in sorted(references.items())
    }


def _value_bridge(references: Mapping[str, ValueReference]) -> str:
    specs = repr(_selector_specs(references))
    private_query_keys = f"frozenset({tuple(sorted(PRIVATE_QUERY_KEYS))!r})"
    return f'''@app.cell(hide_code=True)
def __marimo_studio_values():
    import dataclasses as _studio_dataclasses
    import json as _studio_json
    from collections.abc import Mapping as _StudioMapping
    from marimo._runtime.context import get_context as _studio_get_context
    from marimo._runtime.functions import Function as _StudioFunction

    @_studio_dataclasses.dataclass
    class _StudioReadValuesArgs:
        selectors: list[str]
        max_value_bytes: int = {MAX_VALUE_BYTES}

    @_studio_dataclasses.dataclass
    class _StudioSyncQueryArgs:
        query: dict[str, str | list[str]]

    _studio_specs = {specs}
    _studio_private_query_keys = {private_query_keys}
    _studio_context = _studio_get_context()

    def _studio_error(code, message):
        try:
            text = str(message)
        except Exception:
            text = "The operation failed without a printable message."
        if len(text) > {MAX_ERROR_MESSAGE_LENGTH}:
            text = text[:{MAX_ERROR_MESSAGE_LENGTH}] + "…"
        return {{"code": code, "message": text}}

    def _studio_payload(values, errors):
        payload = {{"values": values, "errors": errors}}
        encoded = _studio_json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) <= {MAX_VALUE_BYTES}:
            return payload
        return {{
            "values": {{}},
            "errors": {{
                "*": _studio_error(
                    "response-too-large",
                    "The value response exceeds the aggregate byte limit.",
                )
            }},
        }}

    def _studio_resolve(namespace, selector):
        variable, path = _studio_specs[selector]
        if variable not in namespace:
            raise KeyError(f"Variable {{variable!r}} is not defined")
        current = namespace[variable]
        for kind, key in path:
            if kind == "attribute":
                if isinstance(current, _StudioMapping) and key in current:
                    current = current[key]
                else:
                    current = getattr(current, key)
            else:
                current = current[key]
        return current

    def _studio_read(args):
        values = {{}}
        errors = {{}}
        selectors = tuple(dict.fromkeys(args.selectors))
        if len(selectors) > {MAX_SELECTOR_COUNT}:
            return _studio_payload(
                values,
                {{
                    "*": _studio_error(
                        "too-many-selectors",
                        "A value request may contain at most "
                        "{MAX_SELECTOR_COUNT} selectors.",
                    )
                }},
            )
        limit = max(1, min(args.max_value_bytes, {MAX_VALUE_BYTES}))
        total = 0
        with _studio_context._kernel.lock_globals():
            namespace = _studio_context.globals
            for selector in selectors:
                if len(selector) > {MAX_SELECTOR_LENGTH}:
                    errors[selector] = _studio_error(
                        "selector-too-long",
                        "Value selectors may contain at most "
                        "{MAX_SELECTOR_LENGTH} characters.",
                    )
                    continue
                if selector not in _studio_specs:
                    errors[selector] = _studio_error(
                        "unknown-selector",
                        f"Selector {{selector!r}} is not present in a configured view.",
                    )
                    continue
                try:
                    value = _studio_resolve(namespace, selector)
                except Exception as error:
                    errors[selector] = _studio_error(
                        "value-path-unavailable",
                        f"Selector {{selector!r}} could not be resolved: {{error}}",
                    )
                    continue
                try:
                    encoded = _studio_json.dumps(
                        value,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                except Exception as error:
                    errors[selector] = _studio_error(
                        "not-json-serializable",
                        f"Selector {{selector!r}} cannot be serialized "
                        f"as JSON: {{error}}",
                    )
                    continue
                size = len(encoded.encode("utf-8"))
                if size > limit:
                    errors[selector] = _studio_error(
                        "value-too-large",
                        f"Selector {{selector!r}} exceeds the {{limit}}-byte limit.",
                    )
                    continue
                if total + size > {MAX_VALUE_BYTES}:
                    errors[selector] = _studio_error(
                        "response-too-large",
                        "The value response exceeds the aggregate byte limit.",
                    )
                    continue
                total += size
                values[selector] = _studio_json.loads(encoded)
        return _studio_payload(values, errors)

    def _studio_sync_query(args):
        params = _studio_context.query_params
        current = dict(params.to_dict())
        for key in current.keys() - args.query.keys() - _studio_private_query_keys:
            params.remove(key)
        for key, value in args.query.items():
            if current.get(key) != value:
                params.set(key, value)

    _studio_context.function_registry.register(
        "_marimo_studio",
        _StudioFunction("read_values", _StudioReadValuesArgs, _studio_read),
    )
    _studio_context.function_registry.register(
        "_marimo_studio",
        _StudioFunction("sync_query", _StudioSyncQueryArgs, _studio_sync_query),
    )
    return

'''


def browser_notebook_source(
    path: Path,
    source: str,
    references: Mapping[str, ValueReference],
) -> str:
    """Return source for a full Pyodide notebook runtime."""
    sanitized = _sanitized_metadata(source, path)
    bridge = _value_bridge(references)
    guard = run_guard_line(sanitized)
    if guard is None:
        separator = "" if not sanitized or sanitized.endswith("\n") else "\n"
        return sanitized + separator + "\n" + bridge
    lines = sanitized.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[: guard - 1])
    return sanitized[:offset] + bridge + sanitized[offset:]
