"""Adapt a Marimo notebook for the browser runtime."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path

from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio._compat.notebook import run_guard_line
from marimo_studio._urls import PRIVATE_QUERY_KEYS
from marimo_studio._workspace.metadata import (
    _document,
    _replace_metadata,
    set_package_requirement,
)
from marimo_studio.types import ValueReference
from marimo_studio.values import MAX_OUTPUT_SELECTORS

MAX_VALUE_SELECTOR_COUNT = 100
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


def _value_bridge(
    value_references: Mapping[str, ValueReference],
    output_references: Mapping[str, ValueReference],
) -> str:
    specs = repr(selector_specs(value_references))
    output_specs = repr(selector_specs(output_references))
    private_query_keys = f"frozenset({tuple(sorted(PRIVATE_QUERY_KEYS))!r})"
    return f'''@app.cell(hide_code=True)
def __marimo_studio_values():
    import dataclasses as _studio_dataclasses
    import gc as _studio_gc
    import hashlib as _studio_hashlib
    import json as _studio_json
    import time as _studio_time
    from collections.abc import Mapping as _StudioMapping
    from marimo._runtime.context import get_context as _studio_get_context
    from marimo._runtime.functions import Function as _StudioFunction
    from marimo._messaging.notification import (
        RemoveUIElementsNotification as _StudioRemoveUIElementsNotification,
    )
    from marimo._messaging.notification_utils import (
        broadcast_notification as _studio_broadcast_notification,
    )
    from marimo._output.formatting import try_format as _studio_try_format
    from marimo._types.ids import CellId_t as _StudioCellId

    @_studio_dataclasses.dataclass
    class _StudioReadValuesArgs:
        selectors: list[str]
        max_value_bytes: int = {MAX_VALUE_BYTES}

    @_studio_dataclasses.dataclass
    class _StudioRenderValuesArgs:
        selectors: list[str]
        active_selectors: list[str]
        consumer_id: str
        max_output_bytes: int = {MAX_VALUE_BYTES}

    @_studio_dataclasses.dataclass
    class _StudioSyncProjectionSpecsArgs:
        value_specs: dict
        output_specs: dict

    @_studio_dataclasses.dataclass
    class _StudioSyncQueryArgs:
        query: dict[str, str | list[str]]
        operation_id: str = ""

    _studio_specs = {specs}
    _studio_output_specs = {output_specs}
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

    def _studio_resolve(specifications, namespace, selector):
        variable, path = specifications[selector]
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
        if len(selectors) > {MAX_VALUE_SELECTOR_COUNT}:
            return _studio_payload(
                values,
                {{
                    "*": _studio_error(
                        "too-many-selectors",
                        "A value request may contain at most "
                        "{MAX_VALUE_SELECTOR_COUNT} selectors.",
                    )
                }},
            )
        limit = max(1, min(args.max_value_bytes, {MAX_VALUE_BYTES}))
        total = 0
        with _studio_context._kernel.lock_globals():
            namespace = _studio_context.globals
            for selector in selectors:
                if selector not in _studio_specs:
                    errors[selector] = _studio_error(
                        "unknown-selector",
                        f"Selector {{selector!r}} is not present in a configured view.",
                    )
                    continue
                try:
                    value = _studio_resolve(_studio_specs, namespace, selector)
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

    _studio_active_outputs = {{}}
    _studio_retained_outputs = set()
    _studio_retained_ui = {{}}
    _studio_ui_owners = {{}}
    _studio_pending_notifications = {{}}

    def _studio_owner(consumer_id, selector):
        identity = consumer_id + "\\0" + selector
        digest = _studio_hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return _StudioCellId({OUTPUT_OWNER_PREFIX!r} + digest)

    def _studio_flush_notifications():
        if not _studio_pending_notifications:
            return
        registry = _studio_context.ui_element_registry
        for identity, released in tuple(_studio_pending_notifications.items()):
            owner = _studio_owner(*identity)
            same_element_is_live = False
            for object_id, released_reference in released.items():
                if released_reference is None:
                    continue
                active_reference = registry._objects.get(object_id)
                released_value = released_reference()
                active_value = (
                    active_reference() if active_reference is not None else None
                )
                if released_value is not None and released_value is active_value:
                    same_element_is_live = True
                    break
            if same_element_is_live:
                continue
            _studio_broadcast_notification(
                _StudioRemoveUIElementsNotification(cell_id=owner)
            )
            _studio_pending_notifications.pop(identity, None)

    def _studio_release_ui_elements(owners, referenced):
        registry = _studio_context.ui_element_registry
        candidates = {{
            identity: set(object_ids)
            for identity, object_ids in referenced.items()
        }}
        owner_identities = {{
            owner: identity for identity, owner in owners.items()
        }}
        for object_id, cell_id in tuple(registry._constructing_cells.items()):
            identity = owner_identities.get(cell_id)
            if identity is not None:
                candidates[identity].add(object_id)
        shared = (
            set().union(*_studio_ui_owners.values())
            if _studio_ui_owners
            else set()
        )
        object_ids = set().union(*candidates.values()).difference(shared)
        references = []
        for object_id in object_ids:
            reference = registry._objects.get(object_id)
            value = reference() if reference is not None else None
            python_id = id(value) if value is not None else -1
            bindings = registry._bindings.get(object_id)
            constructing_cell = registry._constructing_cells.get(object_id)
            references.append(
                (object_id, reference, bindings, constructing_cell)
            )
            del value
            _studio_context.function_registry.delete(namespace=object_id)
            registry.delete(object_id, python_id)
        if object_ids:
            _studio_gc.collect()
        for object_id, reference, bindings, constructing_cell in references:
            value = reference() if reference is not None else None
            if value is None:
                continue
            registry._objects[object_id] = reference
            if constructing_cell is not None:
                registry._constructing_cells[object_id] = constructing_cell
            if bindings is not None:
                registry._bindings[object_id] = bindings
            for function in value._args.functions:
                _studio_context.function_registry.register(
                    namespace=object_id,
                    function=function,
                )
            del value
        live = set(registry._objects)
        return {{
            identity: object_ids.intersection(live)
            for identity, object_ids in candidates.items()
        }}

    def _studio_release_many(requested, retry_retained=False):
        released = set(requested)
        cleanup = released.union(
            _studio_retained_outputs if retry_retained else ()
        )
        if not cleanup:
            return
        candidates = {{
            identity: set(_studio_retained_ui.get(identity, ()))
            for identity in cleanup
        }}
        registry = _studio_context.ui_element_registry
        released_references = {{}}
        for identity in released:
            consumer_id, selector = identity
            referenced = _studio_ui_owners.pop(identity, set())
            owner = _studio_owner(*identity)
            released_references[identity] = {{
                object_id: registry._objects.get(object_id)
                for object_id in referenced
                if registry._constructing_cells.get(object_id) == owner
                or object_id.startswith(f"{{owner}}-")
            }}
            candidates.setdefault(identity, set()).update(referenced)
            active = _studio_active_outputs.get(consumer_id)
            if active is not None:
                active.discard(selector)
                if not active:
                    _studio_active_outputs.pop(consumer_id, None)

        if candidates:
            owners = {{
                identity: _studio_owner(*identity) for identity in candidates
            }}
            retained = _studio_release_ui_elements(owners, candidates)
            lifecycle_registry = _studio_context.cell_lifecycle_registry
            for identity, owner in owners.items():
                retained_ui = retained.get(identity, set())
                if retained_ui:
                    _studio_retained_ui[identity] = retained_ui
                else:
                    _studio_retained_ui.pop(identity, None)
                lifecycle_registry.dispose(owner, deletion=False)
                if owner in lifecycle_registry.registry or retained_ui:
                    _studio_retained_outputs.add(identity)
                else:
                    _studio_retained_outputs.discard(identity)

        _studio_pending_notifications.update(released_references)

    def _studio_replacement_resets(consumer_id, selector):
        identity = (consumer_id, selector)
        released = _studio_pending_notifications.pop(identity, {{}})
        registry = _studio_context.ui_element_registry
        resets = []
        for object_id, released_reference in released.items():
            active_reference = registry._objects.get(object_id)
            released_value = (
                released_reference() if released_reference is not None else None
            )
            active_value = (
                active_reference() if active_reference is not None else None
            )
            if released_value is None or released_value is not active_value:
                resets.append(object_id)
            del released_value, active_value
        return sorted(resets)

    def _studio_track_ui_elements(consumer_id, selector, data):
        registry = _studio_context.ui_element_registry
        referenced = {{
            object_id
            for object_id in tuple(registry._objects)
            if f"object-id='{{object_id}}'" in data
            or f'object-id="{{object_id}}"' in data
        }}
        identity = (consumer_id, selector)
        if referenced:
            _studio_ui_owners[identity] = referenced
        else:
            _studio_ui_owners.pop(identity, None)

    def _studio_render(args):
        outputs = {{}}
        errors = {{}}
        selectors = tuple(dict.fromkeys(args.selectors))
        active = tuple(dict.fromkeys(args.active_selectors))
        if (
            len(selectors) > {MAX_OUTPUT_SELECTORS}
            or len(active) > {MAX_OUTPUT_SELECTORS}
        ):
            return {{
                "outputs": {{}},
                "errors": {{
                    "*": _studio_error(
                        "too-many-selectors",
                        "An output request may contain at most "
                        "{MAX_OUTPUT_SELECTORS} selectors.",
                    )
                }},
            }}
        allowed_active = set(active).intersection(_studio_output_specs)
        consumer_id = args.consumer_id
        current = _studio_active_outputs.get(consumer_id, set())
        releases = current.difference(allowed_active).union(
            current.intersection(selectors)
        )
        _studio_release_many(
            ((consumer_id, selector) for selector in releases),
            retry_retained=True,
        )
        failed = set()
        limit = max(1, min(args.max_output_bytes, {MAX_VALUE_BYTES}))
        with _studio_context._kernel.lock_globals():
            namespace = _studio_context.globals
            for selector in selectors:
                if selector not in _studio_output_specs:
                    errors[selector] = _studio_error(
                        "unknown-selector",
                        f"Selector {{selector!r}} is not present in a configured view.",
                    )
                    continue
                if selector not in allowed_active:
                    errors[selector] = _studio_error(
                        "inactive-selector",
                        f"Selector {{selector!r}} is not mounted in the presentation.",
                    )
                    continue
                variable = _studio_output_specs[selector][0]
                if variable not in namespace:
                    errors[selector] = _studio_error(
                        "missing-variable",
                        f"Variable {{variable!r}} is not defined",
                    )
                    continue
                try:
                    value = _studio_resolve(
                        _studio_output_specs, namespace, selector
                    )
                except Exception as error:
                    errors[selector] = _studio_error(
                        "value-path-unavailable",
                        f"Selector {{selector!r}} could not be resolved: {{error}}",
                    )
                    continue
                owner = _studio_owner(consumer_id, selector)
                try:
                    with _studio_context.with_cell_id(owner):
                        with _studio_context.provide_ui_ids(str(owner)):
                            formatted = _studio_try_format(value)
                            if formatted.exception is not None:
                                formatted = _studio_try_format(
                                    value, include_opinionated=False
                                )
                except BaseException as error:
                    failed.add((consumer_id, selector))
                    errors[selector] = _studio_error(
                        "output-format-error",
                        f"Selector {{selector!r}} could not be formatted: {{error}}",
                    )
                    continue
                if formatted.traceback is not None:
                    failed.add((consumer_id, selector))
                    detail = (
                        str(formatted.exception)
                        if formatted.exception is not None
                        else "The value representation failed."
                    )
                    errors[selector] = _studio_error(
                        "output-format-error",
                        f"Selector {{selector!r}} could not be formatted: {{detail}}",
                    )
                    continue
                rendered = {{
                    "ownerCellId": str(owner),
                    "mimetype": str(formatted.mimetype),
                    "data": formatted.data,
                    "timestamp": _studio_time.time(),
                    "resetUiObjectIds": _studio_replacement_resets(
                        consumer_id, selector
                    ),
                }}
                size = len(
                    _studio_json.dumps(
                        rendered,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                if size > limit:
                    failed.add((consumer_id, selector))
                    errors[selector] = _studio_error(
                        "output-too-large",
                        f"Selector {{selector!r}} exceeds the {{limit}}-byte limit.",
                    )
                    continue
                _studio_track_ui_elements(
                    consumer_id, selector, rendered["data"]
                )
                _studio_active_outputs.setdefault(consumer_id, set()).add(selector)
                outputs[selector] = rendered
        if failed:
            _studio_release_many(failed)
        _studio_flush_notifications()
        result = {{"outputs": outputs, "errors": errors}}
        encoded = _studio_json.dumps(
            result,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) <= limit:
            return result
        _studio_release_many(
            (consumer_id, selector) for selector in outputs
        )
        _studio_flush_notifications()
        return {{
            "outputs": {{}},
            "errors": {{
                "*": _studio_error(
                    "response-too-large",
                    "The output response exceeds the aggregate byte limit.",
                )
            }},
        }}

    def _studio_sync_projection_specs(args):
        next_output_specs = dict(args.output_specs)
        releases = (
            (consumer_id, selector)
            for consumer_id, selectors in tuple(_studio_active_outputs.items())
            for selector in tuple(selectors.difference(next_output_specs))
        )
        _studio_release_many(releases)
        _studio_flush_notifications()
        _studio_specs.clear()
        _studio_specs.update(args.value_specs)
        _studio_output_specs.clear()
        _studio_output_specs.update(next_output_specs)

    class _StudioOutputLifecycle:
        def create(self, context):
            del context

        def dispose(self, context, deletion):
            del context, deletion
            active = (
                (consumer_id, selector)
                for consumer_id, selectors in tuple(
                    _studio_active_outputs.items()
                )
                for selector in tuple(selectors)
            )
            _studio_release_many(active, retry_retained=True)
            _studio_flush_notifications()
            return True

    _studio_context.cell_lifecycle_registry.add(_StudioOutputLifecycle())

    def _studio_sync_query(args):
        params = _studio_context.query_params
        current = dict(params.to_dict())
        query = {{
            key: value
            for key, value in args.query.items()
            if key not in _studio_private_query_keys
        }}
        for key in current.keys() - query.keys() - _studio_private_query_keys:
            params.remove(key)
        for key, value in query.items():
            if current.get(key) != value:
                params.set(key, value)

    _studio_context.function_registry.register(
        "_marimo_studio",
        _StudioFunction("read_values", _StudioReadValuesArgs, _studio_read),
    )
    _studio_context.function_registry.register(
        "_marimo_studio",
        _StudioFunction("render_values", _StudioRenderValuesArgs, _studio_render),
    )
    _studio_context.function_registry.register(
        "_marimo_studio",
        _StudioFunction(
            "sync_projection_specs",
            _StudioSyncProjectionSpecsArgs,
            _studio_sync_projection_specs,
        ),
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
    value_references: Mapping[str, ValueReference],
    output_references: Mapping[str, ValueReference] | None = None,
) -> str:
    """Return source for a full Pyodide notebook runtime."""
    sanitized = _sanitized_metadata(source, path)
    bridge = _value_bridge(value_references, output_references or {})
    guard = run_guard_line(sanitized)
    if guard is None:
        separator = "" if not sanitized or sanitized.endswith("\n") else "\n"
        return sanitized + separator + "\n" + bridge
    lines = sanitized.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[: guard - 1])
    return sanitized[:offset] + bridge + sanitized[offset:]
