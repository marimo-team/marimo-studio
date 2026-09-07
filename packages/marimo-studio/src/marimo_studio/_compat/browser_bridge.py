"""Install Studio's projection services inside a browser-runtime notebook.

The source of ``install_browser_bridge`` is copied into a hidden notebook cell
when Studio prepares saved source for WebAssembly execution. It provides the
browser-worker equivalents of approved value reads, native Marimo output
rendering, public query synchronization, projection readiness, and resource
release without requiring the host-side Studio package in Pyodide.

The bridge accepts only mounts configured for the current page, applies
bounded target and response rules inside the worker, and ignores updates from
an older page or query version. It owns projected controls, widgets, functions,
and virtual files until their mount is replaced or removed, then releases those
resources through Marimo's browser kernel lifecycle.
"""

from __future__ import annotations

from marimo_studio._compat.kernel_values.arrow import (
    _ArrowMaterializationRequired,
    _dataframe_ipc,
)


def install_browser_bridge(
    *,
    _studio_config_private_query_keys: frozenset[str],
    _studio_config_output_owner_prefix: str,
    _studio_config_namespace: str,
    _studio_config_max_value_selector_count: int,
    _studio_config_max_value_bytes: int,
    _studio_config_max_error_message_length: int,
    _studio_config_max_value_path_steps: int,
    _studio_config_max_output_selectors: int,
) -> None:
    """Install bounded value, output, and query functions in the active kernel."""
    import dataclasses as _studio_dataclasses
    import gc as _studio_gc
    import hashlib as _studio_hashlib
    import json as _studio_json
    import re as _studio_re
    import time as _studio_time
    from collections.abc import Mapping as _StudioMapping
    from typing import Any as _StudioAny
    from typing import cast as _studio_cast

    from marimo._messaging.notification import (
        RemoveUIElementsNotification as _StudioRemoveUIElementsNotification,
    )
    from marimo._messaging.notification_utils import (
        broadcast_notification as _studio_broadcast_notification,
    )
    from marimo._output.formatting import try_format as _studio_try_format
    from marimo._runtime.cell_lifecycle_item import (
        CellLifecycleItem as _StudioCellLifecycleItem,
    )
    from marimo._runtime.context import get_context as _studio_get_context
    from marimo._runtime.functions import Function as _StudioFunction
    from marimo._runtime.virtual_file import VirtualFile as _StudioVirtualFile
    from marimo._types.ids import CellId_t as _StudioCellId

    _studio_max_value_bytes = _studio_config_max_value_bytes
    _studio_max_value_target_bytes = 4_096
    _studio_max_value_transport_bytes = (
        ((_studio_max_value_bytes + 2) // 3) * 4
        + _studio_config_max_value_selector_count
        * (
            _studio_config_max_error_message_length
            + 2 * _studio_max_value_target_bytes
            + 512
        )
        + 4_096
    )

    @_studio_dataclasses.dataclass
    class _StudioReadValuesArgs:
        revision: str
        projections: list
        active_projections: list
        max_value_bytes: int = _studio_max_value_bytes

    @_studio_dataclasses.dataclass
    class _StudioRenderValuesArgs:
        revision: str
        projections: list
        active_projections: list
        consumer_id: str
        max_output_bytes: int = _studio_max_value_bytes

    @_studio_dataclasses.dataclass
    class _StudioConfigureProjectionArgs:
        revision: str
        generation: int
        mounts: list
        variables: list

    @_studio_dataclasses.dataclass
    class _StudioProjectionBridgeReadyArgs:
        pass

    @_studio_dataclasses.dataclass
    class _StudioSyncQueryArgs:
        query: dict[str, str | list[str]]
        generation: int
        operation_id: str = ""

    class _StudioProjectionError(ValueError):
        def __init__(self, code, message):
            super().__init__(message)
            self.code = code

    _studio_private_query_keys = _studio_config_private_query_keys
    _studio_context = _studio_cast(_StudioAny, _studio_get_context())
    _studio_projection_authorization: dict[str, _StudioAny] = {
        "generation": -1,
        "revision": None,
        "sites": {},
        "variables": frozenset(),
    }
    _studio_identifier = _studio_re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    _studio_index = _studio_re.compile(r"(?:0|[1-9][0-9]*)")
    _studio_json_decoder = _studio_json.JSONDecoder()
    _studio_value_resources = {}

    def _studio_projection_bridge_ready(args):
        del args
        return {"ready": True}

    def _studio_message(message):
        try:
            return str(message)
        except Exception:
            return "The operation failed without a printable message."

    def _studio_error(code, message):
        text = _studio_message(message)
        if len(text) > _studio_config_max_error_message_length:
            text = text[:_studio_config_max_error_message_length] + "…"
        return {"code": code, "message": text}

    def _studio_normalize_utf16(value):
        normalized = []
        index = 0
        while index < len(value):
            codepoint = ord(value[index])
            if 0xD800 <= codepoint <= 0xDBFF:
                if index + 1 >= len(value):
                    raise ValueError("Unpaired UTF-16 surrogate.")
                trailing = ord(value[index + 1])
                if not 0xDC00 <= trailing <= 0xDFFF:
                    raise ValueError("Unpaired UTF-16 surrogate.")
                normalized.append(
                    chr(0x10000 + ((codepoint - 0xD800) << 10) + (trailing - 0xDC00))
                )
                index += 2
                continue
            if 0xDC00 <= codepoint <= 0xDFFF:
                raise ValueError("Unpaired UTF-16 surrogate.")
            normalized.append(value[index])
            index += 1
        return "".join(normalized)

    def _studio_payload(values, errors):
        payload = {"values": values, "errors": errors}
        encoded = _studio_json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) <= _studio_max_value_transport_bytes:
            return payload
        return {
            "values": {},
            "errors": {
                "*": _studio_error(
                    "response-too-large",
                    "The value response exceeds the aggregate byte limit.",
                )
            },
        }

    def _studio_fingerprint(data):
        return "sha256:" + _studio_hashlib.sha256(data).hexdigest()

    def _studio_remove_value_resource(resource):
        if not resource.url.startswith("data:"):
            _studio_context.virtual_file_registry.remove(resource)

    def _studio_release_value_resources():
        for selector in tuple(_studio_value_resources):
            _fingerprint_value, resource = _studio_value_resources[selector]
            _studio_remove_value_resource(resource)
            del _studio_value_resources[selector]

    def _studio_reconcile_value_resources(active):
        for selector in tuple(_studio_value_resources):
            if selector not in active:
                _studio_commit_value_resource(selector, None)

    def _studio_commit_value_resource(selector, staged):
        previous = _studio_value_resources.get(selector)
        if staged is None:
            if previous is not None:
                _studio_remove_value_resource(previous[1])
                del _studio_value_resources[selector]
            return
        fingerprint, resource, reused = staged
        if previous is not None and previous[1] is not resource:
            try:
                _studio_remove_value_resource(previous[1])
            except BaseException:
                if not reused:
                    _studio_remove_value_resource(resource)
                raise
        _studio_value_resources[selector] = (fingerprint, resource)

    def _studio_encode_value(selector, value, limit):
        try:
            ipc = _dataframe_ipc(value)
        except _ArrowMaterializationRequired as error:
            raise _StudioProjectionError(
                "arrow-materialization-required",
                "Materialize the dataframe before projecting it.",
            ) from error
        except (ImportError, ModuleNotFoundError) as error:
            raise _StudioProjectionError(
                "arrow-codec-unavailable",
                f"PyArrow is required for Arrow IPC: {error}",
            ) from error
        except Exception as error:
            raise _StudioProjectionError(
                "arrow-serialization-error",
                f"Selector {selector!r} could not be serialized as Arrow IPC: {error}",
            ) from error
        if ipc is None:
            try:
                text = _studio_json.dumps(
                    value,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            except Exception as error:
                raise _StudioProjectionError(
                    "not-json-serializable",
                    f"Selector {selector!r} cannot be serialized as JSON: {error}",
                ) from error
            data = text.encode("utf-8")
            if len(data) > limit:
                raise _StudioProjectionError(
                    "value-too-large",
                    f"Selector {selector!r} exceeds the {limit}-byte limit.",
                )
            return (
                {
                    "codec": "json-v1",
                    "fingerprint": _studio_fingerprint(data),
                    "value": _studio_json.loads(text),
                },
                len(data),
                None,
            )
        if len(ipc) > limit:
            raise _StudioProjectionError(
                "value-too-large",
                f"Selector {selector!r} exceeds the {limit}-byte limit.",
            )
        fingerprint = _studio_fingerprint(ipc)
        current = _studio_value_resources.get(selector)
        if current is not None and current[0] == fingerprint:
            resource = current[1]
            reused = True
        else:
            resource = _StudioVirtualFile.create_and_register(ipc, "arrow")
            reused = False
        return (
            {
                "codec": "arrow-ipc-v1",
                "fingerprint": fingerprint,
                "dataUrl": resource.url,
                "byteLength": len(ipc),
            },
            len(ipc),
            (fingerprint, resource, reused),
        )

    def _studio_configure_projections(args):
        revision = args.revision
        if not isinstance(revision, str) or not revision:
            raise ValueError("The presentation revision must be a non-empty string.")
        generation = args.generation
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 0
            or generation > 9_007_199_254_740_991
        ):
            raise ValueError("The projection authorization generation is invalid.")
        if not isinstance(args.mounts, list):
            raise ValueError("Projection sites must be an array.")
        sites = {}
        for site in args.mounts:
            if (
                not isinstance(site, dict)
                or set(site) != {"id", "kind", "source", "allowedTargets"}
                or not isinstance(site["id"], str)
                or not site["id"]
                or site["id"] in sites
                or site["kind"] not in {"cell", "output", "value"}
            ):
                raise ValueError("A projection mount is invalid.")
            source = site["source"]
            allowed_targets = site["allowedTargets"]
            if (
                not isinstance(source, dict)
                or set(source) != {"path", "line", "column"}
                or not isinstance(source["path"], str)
                or not source["path"]
                or isinstance(source["line"], bool)
                or not isinstance(source["line"], int)
                or source["line"] < 1
                or isinstance(source["column"], bool)
                or not isinstance(source["column"], int)
                or source["column"] < 1
                or (
                    allowed_targets is not None
                    and (
                        not isinstance(allowed_targets, list)
                        or not allowed_targets
                        or not all(
                            isinstance(target, str) and target
                            for target in allowed_targets
                        )
                        or len(set(allowed_targets)) != len(allowed_targets)
                    )
                )
            ):
                raise ValueError("A projection mount is invalid.")
            sites[site["id"]] = site
        if (
            not isinstance(args.variables, list)
            or not all(
                isinstance(variable, str) and variable for variable in args.variables
            )
            or len(set(args.variables)) != len(args.variables)
        ):
            raise ValueError("Projection variables must be unique names.")
        current_generation = _studio_projection_authorization["generation"]
        if generation < current_generation:
            return {
                "revision": _studio_projection_authorization["revision"],
                "generation": current_generation,
                "applied": False,
            }
        variables = frozenset(args.variables)
        if generation == current_generation:
            if (
                revision != _studio_projection_authorization["revision"]
                or sites != _studio_projection_authorization["sites"]
                or variables != _studio_projection_authorization["variables"]
            ):
                raise ValueError(
                    "One projection authorization generation cannot describe "
                    "different catalogs."
                )
            return {
                "revision": revision,
                "generation": generation,
                "applied": True,
            }
        _studio_release_value_resources()
        _studio_projection_authorization.update(
            generation=generation,
            revision=revision,
            sites=sites,
            variables=variables,
        )
        return {
            "revision": revision,
            "generation": generation,
            "applied": True,
        }

    def _studio_parse_projection_target(target):
        value = target.strip()
        root = _studio_identifier.match(value)
        if root is None:
            raise ValueError("A projection target must start with a variable name.")
        path: list[tuple[str, str | int]] = []
        position = root.end()
        while position < len(value):
            token = value[position]
            if token == ".":
                selected = _studio_identifier.match(value, position + 1)
                if selected is None:
                    raise ValueError("Dot selection requires an object key.")
                if selected.group().startswith("_"):
                    raise ValueError("Private attribute selection is unavailable.")
                path.append(("attribute", selected.group()))
                position = selected.end()
            elif token == "[":
                position += 1
                selected_index = _studio_index.match(value, position)
                if selected_index is not None:
                    key = int(selected_index.group())
                    if key > 9_007_199_254_740_991:
                        raise ValueError(
                            "Bracket indexes must be JavaScript safe integers."
                        )
                    position = selected_index.end()
                elif position < len(value) and value[position] == '"':
                    try:
                        key, consumed = _studio_json_decoder.raw_decode(
                            value[position:]
                        )
                    except _studio_json.JSONDecodeError as error:
                        raise ValueError(
                            "Bracket object keys must be JSON strings."
                        ) from error
                    if not isinstance(key, str):
                        raise ValueError("Bracket object keys must be JSON strings.")
                    try:
                        key = _studio_normalize_utf16(key)
                    except ValueError as error:
                        raise _StudioProjectionError(
                            "projection-unpaired-surrogate",
                            "Projection targets and instance IDs require "
                            "well-formed Unicode.",
                        ) from error
                    position += consumed
                else:
                    raise ValueError(
                        "Brackets require a non-negative integer or JSON string."
                    )
                if position >= len(value) or value[position] != "]":
                    raise ValueError("Bracket selection requires a closing ].")
                path.append(("item", key))
                position += 1
            else:
                raise ValueError(
                    "A projection target may contain dot selection and "
                    "bracket indexing."
                )
            if len(path) > _studio_config_max_value_path_steps:
                raise ValueError("The projection selector path is too deep.")
        return root.group(), tuple(path)

    def _studio_projection_specs(revision, projections, kind):
        if revision != _studio_projection_authorization["revision"]:
            raise ValueError("The projection request revision is not active.")
        if not isinstance(projections, list):
            raise ValueError("Projection requests must be an array.")
        specifications = {}
        for request in projections:
            if (
                not isinstance(request, dict)
                or set(request) != {"siteId", "instanceId", "target"}
                or not isinstance(request["siteId"], str)
                or not request["siteId"]
                or not isinstance(request["instanceId"], str)
                or not request["instanceId"]
                or not isinstance(request["target"], str)
                or not request["target"]
            ):
                raise ValueError("A projection request is invalid.")
            try:
                _studio_normalize_utf16(request["instanceId"])
                target = _studio_normalize_utf16(request["target"])
            except ValueError as error:
                raise _StudioProjectionError(
                    "projection-unpaired-surrogate",
                    "Projection targets and instance IDs require well-formed Unicode.",
                ) from error
            if len(target.encode("utf-8")) > _studio_max_value_target_bytes:
                raise ValueError("The projection target exceeds the byte limit.")
            site = _studio_projection_authorization["sites"].get(request["siteId"])
            if site is None or site["kind"] != kind:
                raise ValueError("The projection site is unavailable for this kind.")
            allowed_targets = site["allowedTargets"]
            if allowed_targets is not None and target not in allowed_targets:
                raise ValueError("The projection target is not allowed by this mount.")
            variable, path = _studio_parse_projection_target(target)
            if variable not in _studio_projection_authorization["variables"]:
                raise ValueError(
                    "The projection variable has no unique notebook producer."
                )
            specifications[request["target"]] = (variable, path)
        return specifications

    def _studio_resolve(specifications, namespace, selector):
        variable, path = specifications[selector]
        if variable not in namespace:
            raise KeyError(f"Variable {variable!r} is not defined")
        current = namespace[variable]
        for kind, key in path:
            if kind == "attribute":
                if isinstance(current, _StudioMapping) and key in current:
                    current = current[key]
                else:
                    current = getattr(current, key)
            else:
                current = _studio_cast(_StudioAny, current)[key]
        return current

    def _studio_read(args):
        values = {}
        errors = {}
        try:
            specifications = _studio_projection_specs(
                args.revision, args.projections, "value"
            )
            active_specifications = _studio_projection_specs(
                args.revision, args.active_projections, "value"
            )
        except Exception as error:
            return _studio_payload(
                values,
                {
                    "*": _studio_error(
                        getattr(
                            error,
                            "code",
                            "projection-authorization-invalid",
                        ),
                        error,
                    )
                },
            )
        selectors = tuple(specifications)
        active = tuple(active_specifications)
        if (
            len(selectors) > _studio_config_max_value_selector_count
            or len(active) > _studio_config_max_value_selector_count
        ):
            return _studio_payload(
                values,
                {
                    "*": _studio_error(
                        "too-many-selectors",
                        "A value request may contain at most "
                        f"{_studio_config_max_value_selector_count} selectors.",
                    )
                },
            )
        limit = max(1, min(args.max_value_bytes, _studio_config_max_value_bytes))
        total = 0
        allowed_active = set(active)
        _studio_reconcile_value_resources(allowed_active)
        with _studio_context._kernel.lock_globals():
            namespace = _studio_context.globals
            for selector in selectors:
                if selector not in allowed_active:
                    _studio_commit_value_resource(selector, None)
                    errors[selector] = _studio_error(
                        "inactive-selector",
                        f"Selector {selector!r} is not mounted in the presentation.",
                    )
                    continue
                if active_specifications[selector] != specifications[selector]:
                    _studio_commit_value_resource(selector, None)
                    errors[selector] = _studio_error(
                        "invalid-selector-spec",
                        f"Selector {selector!r} has conflicting active specs.",
                    )
                    continue
                try:
                    value = _studio_resolve(specifications, namespace, selector)
                except Exception as error:
                    _studio_commit_value_resource(selector, None)
                    errors[selector] = _studio_error(
                        "value-path-unavailable",
                        f"Selector {selector!r} could not be resolved: {error}",
                    )
                    continue
                try:
                    encoded, size, resource = _studio_encode_value(
                        selector, value, limit
                    )
                except _StudioProjectionError as error:
                    _studio_commit_value_resource(selector, None)
                    errors[selector] = _studio_error(
                        error.code,
                        error,
                    )
                    continue
                if total + size > _studio_config_max_value_bytes:
                    if resource is not None and not resource[2]:
                        _studio_remove_value_resource(resource[1])
                    errors[selector] = _studio_error(
                        "response-too-large",
                        "The value response exceeds the aggregate byte limit.",
                    )
                    _studio_commit_value_resource(selector, None)
                    continue
                try:
                    _studio_commit_value_resource(selector, resource)
                except BaseException as error:
                    _studio_commit_value_resource(selector, None)
                    errors[selector] = _studio_error(
                        "value-resource-error",
                        f"Selector {selector!r} could not publish its value: {error}",
                    )
                    continue
                total += size
                values[selector] = encoded
        return _studio_payload(values, errors)

    _studio_active_outputs: dict[str, set[str]] = {}
    _studio_releasing_outputs: set[tuple[str, str]] = set()
    _studio_release_references: dict[tuple[str, str], dict[_StudioAny, _StudioAny]] = {}
    _studio_retained_outputs: set[tuple[str, str]] = set()
    _studio_retained_ui: dict[tuple[str, str], set[_StudioAny]] = {}
    _studio_ui_owners: dict[tuple[str, str], set[_StudioAny]] = {}
    _studio_pending_notifications: dict[
        tuple[str, str], dict[_StudioAny, _StudioAny]
    ] = {}

    def _studio_owner(consumer_id, selector):
        identity = consumer_id + "\\0" + selector
        digest = _studio_hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return _StudioCellId(_studio_config_output_owner_prefix + digest)

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
        candidates = {
            identity: set(object_ids) for identity, object_ids in referenced.items()
        }
        owner_identities = {owner: identity for identity, owner in owners.items()}
        for object_id, cell_id in tuple(registry._constructing_cells.items()):
            identity = owner_identities.get(cell_id)
            if identity is not None:
                candidates[identity].add(object_id)
        shared_owners = (
            referenced
            for identity, referenced in _studio_ui_owners.items()
            if identity not in _studio_releasing_outputs
        )
        shared = set().union(*shared_owners)
        object_ids = set().union(*candidates.values()).difference(shared)
        references = []
        for object_id in object_ids:
            reference = registry._objects.get(object_id)
            if reference is None:
                continue
            value = reference()
            python_id = id(value) if value is not None else -1
            bindings = registry._bindings.get(object_id)
            constructing_cell = registry._constructing_cells.get(object_id)
            references.append((object_id, reference, bindings, constructing_cell))
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
        return {
            identity: object_ids.intersection(live)
            for identity, object_ids in candidates.items()
        }

    def _studio_release_many(requested, retry_retained=False):
        released = set(requested)
        if (
            not released
            and not _studio_releasing_outputs
            and (not retry_retained or not _studio_retained_outputs)
        ):
            return
        registry = _studio_context.ui_element_registry
        for identity in released:
            consumer_id, selector = identity
            if identity not in _studio_releasing_outputs:
                referenced = set(_studio_ui_owners.get(identity, ()))
                owner = _studio_owner(*identity)
                _studio_release_references[identity] = {
                    object_id: registry._objects.get(object_id)
                    for object_id in referenced
                    if registry._constructing_cells.get(object_id) == owner
                    or object_id.startswith(f"{owner}-")
                }
                _studio_releasing_outputs.add(identity)
            active = _studio_active_outputs.get(consumer_id)
            if active is not None:
                active.discard(selector)
                if not active:
                    _studio_active_outputs.pop(consumer_id, None)

        cleanup = _studio_releasing_outputs.union(
            _studio_retained_outputs if retry_retained else ()
        )
        if not cleanup:
            return
        candidates = {
            identity: set(_studio_retained_ui.get(identity, ())) for identity in cleanup
        }
        for identity in cleanup:
            candidates[identity].update(_studio_ui_owners.get(identity, ()))

        if candidates:
            owners = {identity: _studio_owner(*identity) for identity in candidates}
            retained = _studio_release_ui_elements(owners, candidates)
            lifecycle_registry = _studio_context.cell_lifecycle_registry
            failure = None
            for identity, owner in owners.items():
                try:
                    lifecycle_registry.dispose(owner, deletion=False)
                except BaseException as error:
                    if failure is None:
                        failure = error
                    continue
                retained_ui = retained.get(identity, set())
                if retained_ui:
                    _studio_retained_ui[identity] = retained_ui
                else:
                    _studio_retained_ui.pop(identity, None)
                if owner in lifecycle_registry.registry or retained_ui:
                    _studio_retained_outputs.add(identity)
                else:
                    _studio_retained_outputs.discard(identity)
                if identity in _studio_releasing_outputs:
                    pending = _studio_pending_notifications.setdefault(identity, {})
                    pending.update(_studio_release_references.pop(identity, {}))
                    _studio_ui_owners.pop(identity, None)
                    _studio_releasing_outputs.discard(identity)
            if failure is not None:
                raise failure

    def _studio_replacement_resets(consumer_id, selector):
        identity = (consumer_id, selector)
        released = _studio_pending_notifications.pop(identity, {})
        registry = _studio_context.ui_element_registry
        resets = []
        for object_id, released_reference in released.items():
            active_reference = registry._objects.get(object_id)
            released_value = (
                released_reference() if released_reference is not None else None
            )
            active_value = active_reference() if active_reference is not None else None
            if released_value is None or released_value is not active_value:
                resets.append(object_id)
            del released_value, active_value
        return sorted(resets)

    def _studio_track_ui_elements(consumer_id, selector, data):
        registry = _studio_context.ui_element_registry
        referenced = {
            object_id
            for object_id in tuple(registry._objects)
            if f"object-id='{object_id}'" in data or f'object-id="{object_id}"' in data
        }
        identity = (consumer_id, selector)
        if referenced:
            _studio_ui_owners[identity] = referenced
        else:
            _studio_ui_owners.pop(identity, None)

    def _studio_render(args):
        outputs = {}
        errors = {}
        try:
            specifications = _studio_projection_specs(
                args.revision, args.projections, "output"
            )
            active_specifications = _studio_projection_specs(
                args.revision, args.active_projections, "output"
            )
        except Exception as error:
            return {
                "outputs": {},
                "errors": {
                    "*": _studio_error(
                        getattr(
                            error,
                            "code",
                            "projection-authorization-invalid",
                        ),
                        error,
                    )
                },
            }
        selectors = tuple(specifications)
        active = tuple(active_specifications)
        if (
            len(selectors) > _studio_config_max_output_selectors
            or len(active) > _studio_config_max_output_selectors
        ):
            return {
                "outputs": {},
                "errors": {
                    "*": _studio_error(
                        "too-many-selectors",
                        "An output request may contain at most "
                        f"{_studio_config_max_output_selectors} selectors.",
                    )
                },
            }
        allowed_active = set(active)
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
        limit = max(1, min(args.max_output_bytes, _studio_config_max_value_bytes))
        with _studio_context._kernel.lock_globals():
            namespace = _studio_context.globals
            for selector in selectors:
                if selector not in allowed_active:
                    errors[selector] = _studio_error(
                        "inactive-selector",
                        f"Selector {selector!r} is not mounted in the presentation.",
                    )
                    continue
                if active_specifications[selector] != specifications[selector]:
                    errors[selector] = _studio_error(
                        "invalid-selector-spec",
                        f"Selector {selector!r} has conflicting active specs.",
                    )
                    continue
                variable = specifications[selector][0]
                if variable not in namespace:
                    errors[selector] = _studio_error(
                        "missing-variable",
                        f"Variable {variable!r} is not defined",
                    )
                    continue
                try:
                    value = _studio_resolve(specifications, namespace, selector)
                except Exception as error:
                    errors[selector] = _studio_error(
                        "value-path-unavailable",
                        f"Selector {selector!r} could not be resolved: {error}",
                    )
                    continue
                owner = _studio_owner(consumer_id, selector)
                try:
                    with (
                        _studio_context.with_cell_id(owner),
                        _studio_context.provide_ui_ids(str(owner)),
                    ):
                        formatted = _studio_try_format(value)
                        if formatted.exception is not None:
                            formatted = _studio_try_format(
                                value, include_opinionated=False
                            )
                except BaseException as error:
                    failed.add((consumer_id, selector))
                    detail = _studio_message(error)
                    errors[selector] = _studio_error(
                        "output-format-error",
                        f"Selector {selector!r} could not be formatted: {detail}",
                    )
                    continue
                if formatted.traceback is not None:
                    failed.add((consumer_id, selector))
                    detail = (
                        _studio_message(formatted.exception)
                        if formatted.exception is not None
                        else "The value representation failed."
                    )
                    errors[selector] = _studio_error(
                        "output-format-error",
                        f"Selector {selector!r} could not be formatted: {detail}",
                    )
                    continue
                try:
                    rendered = {
                        "ownerCellId": str(owner),
                        "mimetype": str(formatted.mimetype),
                        "data": formatted.data,
                        "timestamp": _studio_time.time(),
                        "resetUiObjectIds": _studio_replacement_resets(
                            consumer_id, selector
                        ),
                    }
                    size = len(
                        _studio_json.dumps(
                            rendered,
                            allow_nan=False,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                except BaseException as error:
                    failed.add((consumer_id, selector))
                    detail = _studio_message(error)
                    errors[selector] = _studio_error(
                        "output-format-error",
                        f"Selector {selector!r} could not be encoded: {detail}",
                    )
                    continue
                if size > limit:
                    failed.add((consumer_id, selector))
                    errors[selector] = _studio_error(
                        "output-too-large",
                        f"Selector {selector!r} exceeds the {limit}-byte limit.",
                    )
                    continue
                try:
                    _studio_track_ui_elements(consumer_id, selector, rendered["data"])
                except BaseException as error:
                    failed.add((consumer_id, selector))
                    detail = _studio_message(error)
                    errors[selector] = _studio_error(
                        "output-format-error",
                        f"Selector {selector!r} could not be tracked: {detail}",
                    )
                    continue
                _studio_active_outputs.setdefault(consumer_id, set()).add(selector)
                outputs[selector] = rendered
        if failed:
            _studio_release_many(failed)
        _studio_flush_notifications()
        result = {"outputs": outputs, "errors": errors}
        encoded = _studio_json.dumps(
            result,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) <= limit:
            return result
        _studio_release_many((consumer_id, selector) for selector in outputs)
        _studio_flush_notifications()
        return {
            "outputs": {},
            "errors": {
                "*": _studio_error(
                    "response-too-large",
                    "The output response exceeds the aggregate byte limit.",
                )
            },
        }

    _studio_bridge_functions: dict[str, _StudioAny] = {}
    _studio_host_state: dict[str, _StudioAny] = {
        "closed": False,
        "query_generation": -1,
    }

    def _studio_unregister_bridge():
        if not _studio_bridge_functions:
            return
        registry = _studio_context.function_registry
        if all(
            registry.get_function(_studio_config_namespace, name) is function
            for name, function in _studio_bridge_functions.items()
        ):
            registry.delete(_studio_config_namespace)
        _studio_bridge_functions.clear()

    class _StudioOutputLifecycle(_StudioCellLifecycleItem):
        def create(self, context):
            del context

        def dispose(self, context, deletion):
            del context, deletion
            if _studio_host_state["closed"]:
                return True
            try:
                _studio_release_value_resources()
            except BaseException:
                return False
            active = (
                (consumer_id, selector)
                for consumer_id, selectors in tuple(_studio_active_outputs.items())
                for selector in tuple(selectors)
            )
            try:
                _studio_release_many(active, retry_retained=True)
                _studio_flush_notifications()
            except BaseException:
                return False
            if _studio_releasing_outputs or _studio_retained_outputs:
                return False
            try:
                _studio_unregister_bridge()
            except BaseException:
                return False
            _studio_host_state["closed"] = True
            return True

    def _studio_sync_query(args):
        if (
            isinstance(args.generation, bool)
            or not isinstance(args.generation, int)
            or args.generation < 0
            or args.generation > 9_007_199_254_740_991
        ):
            raise _StudioProjectionError(
                "invalid-query-generation",
                "The query generation must be a non-negative safe integer.",
            )
        if args.generation < _studio_host_state["query_generation"]:
            return {"generation": args.generation, "applied": False}
        if args.generation == _studio_host_state["query_generation"]:
            return {"generation": args.generation, "applied": True}
        params = _studio_context.query_params
        current = dict(params.to_dict())
        query = {
            key: value
            for key, value in args.query.items()
            if key not in _studio_private_query_keys
        }
        for key in current.keys() - query.keys() - _studio_private_query_keys:
            params.remove(key)
        for key, value in query.items():
            if current.get(key) != value:
                params.set(key, value)
        _studio_host_state["query_generation"] = args.generation
        return {"generation": args.generation, "applied": True}

    _studio_functions = (
        _StudioFunction(
            "projection_bridge_ready",
            _StudioProjectionBridgeReadyArgs,
            _studio_projection_bridge_ready,
        ),
        _StudioFunction(
            "configure_projections",
            _StudioConfigureProjectionArgs,
            _studio_configure_projections,
        ),
        _StudioFunction("read_values", _StudioReadValuesArgs, _studio_read),
        _StudioFunction("render_values", _StudioRenderValuesArgs, _studio_render),
        _StudioFunction("sync_query", _StudioSyncQueryArgs, _studio_sync_query),
    )
    try:
        for function in _studio_functions:
            _studio_context.function_registry.register(
                _studio_config_namespace,
                function,
            )
            _studio_bridge_functions[function.name] = function
        _studio_context.cell_lifecycle_registry.add(_StudioOutputLifecycle())
    except BaseException as setup_error:
        try:
            _studio_context.function_registry.delete(_studio_config_namespace)
        except BaseException as cleanup_error:
            raise setup_error from cleanup_error
        _studio_bridge_functions.clear()
        raise
    return
