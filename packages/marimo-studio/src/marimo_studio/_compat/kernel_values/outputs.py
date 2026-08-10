"""Format permitted notebook values through Marimo's native output registry."""

from __future__ import annotations

import gc
import hashlib
import json
import time
from collections.abc import Iterable, Mapping
from typing import Any

from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
from marimo_studio.types import (
    OutputRenderResult,
    RenderedOutput,
    ValueReadError,
)
from marimo_studio.values import parse_value_reference, resolve_value_reference


def _owner_id(consumer_id: str, selector: str) -> str:
    digest = hashlib.sha256(f"{consumer_id}\0{selector}".encode()).hexdigest()
    return f"{OUTPUT_OWNER_PREFIX}{digest}"


def _message(error: BaseException) -> str:
    try:
        return str(error)
    except Exception:
        return "The formatter failed without a printable message."


def _encoded_size(value: object) -> int:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


class KernelOutputRenderer:
    """Own native Marimo output resources for active presentation selectors."""

    def __init__(self, context: Any) -> None:
        self._context = context
        self._active: dict[str, set[str]] = {}
        self._retained: set[tuple[str, str]] = set()
        self._retained_ui: dict[tuple[str, str], set[str]] = {}
        self._ui_owners: dict[tuple[str, str], set[str]] = {}
        self._pending_notifications: dict[tuple[str, str], dict[str, Any]] = {}

    def render(
        self,
        namespace: Mapping[str, object],
        selectors: tuple[str, ...],
        active_selectors: tuple[str, ...],
        allowed: set[str],
        *,
        consumer_id: str,
        max_output_bytes: int,
    ) -> OutputRenderResult:
        selectors = tuple(dict.fromkeys(selectors))
        active = set(active_selectors).intersection(allowed)
        current = self._active.get(consumer_id, set())
        releases = current.difference(active).union(current.intersection(selectors))
        self._release_many(
            ((consumer_id, selector) for selector in releases),
            retry_retained=True,
        )

        outputs: dict[str, RenderedOutput] = {}
        errors: dict[str, ValueReadError] = {}
        failed: set[tuple[str, str]] = set()
        for selector in selectors:
            if selector not in allowed:
                errors[selector] = ValueReadError(
                    "unknown-selector",
                    f"Selector {selector!r} is not present in a configured view.",
                )
                continue
            if selector not in active:
                errors[selector] = ValueReadError(
                    "inactive-selector",
                    f"Selector {selector!r} is not mounted in the presentation.",
                )
                continue
            try:
                reference = parse_value_reference(selector)
            except ValueError as error:
                errors[selector] = ValueReadError("invalid-selector", str(error))
                continue
            if reference.variable not in namespace:
                errors[selector] = ValueReadError(
                    "missing-variable",
                    f"Variable {reference.variable!r} is not defined",
                )
                continue
            try:
                value = resolve_value_reference(namespace, reference)
            except Exception as error:
                errors[selector] = ValueReadError(
                    "value-path-unavailable",
                    f"Selector {selector!r} could not be resolved: {error}",
                )
                continue

            output, error = self._format(consumer_id, selector, value)
            if error is not None:
                failed.add((consumer_id, selector))
                errors[selector] = error
                continue
            assert output is not None
            size = _encoded_size(output.to_dict())
            if size > max_output_bytes:
                failed.add((consumer_id, selector))
                errors[selector] = ValueReadError(
                    "output-too-large",
                    f"Selector {selector!r} exceeds the {max_output_bytes}-byte limit.",
                )
                continue
            self._active.setdefault(consumer_id, set()).add(selector)
            outputs[selector] = output
        if failed:
            self._release_many(failed)
        self._flush_notifications()
        result = OutputRenderResult(outputs=outputs, errors=errors)
        if _encoded_size(result.to_dict()) <= max_output_bytes:
            return result
        self._release_many((consumer_id, selector) for selector in outputs)
        self._flush_notifications()
        return OutputRenderResult(
            outputs={},
            errors={
                "*": ValueReadError(
                    "response-too-large",
                    "The output response exceeds the aggregate byte limit.",
                )
            },
        )

    def close(self) -> None:
        active = (
            (consumer_id, selector)
            for consumer_id, selectors in tuple(self._active.items())
            for selector in tuple(selectors)
        )
        self._release_many(active, retry_retained=True)
        self._flush_notifications()

    def _format(
        self,
        consumer_id: str,
        selector: str,
        value: object,
    ) -> tuple[RenderedOutput | None, ValueReadError | None]:
        from marimo._output.formatting import try_format
        from marimo._types.ids import CellId_t

        owner = CellId_t(_owner_id(consumer_id, selector))
        try:
            with (
                self._context.with_cell_id(owner),
                self._context.provide_ui_ids(str(owner)),
            ):
                formatted = try_format(value)
                if formatted.exception is not None:
                    formatted = try_format(value, include_opinionated=False)
        except BaseException as error:
            return None, ValueReadError(
                "output-format-error",
                f"Selector {selector!r} could not be formatted: {_message(error)}",
            )
        if formatted.traceback is not None:
            detail = (
                _message(formatted.exception)
                if formatted.exception is not None
                else "The value representation failed."
            )
            return None, ValueReadError(
                "output-format-error",
                f"Selector {selector!r} could not be formatted: {detail}",
            )
        output = RenderedOutput(
            owner_cell_id=str(owner),
            mimetype=str(formatted.mimetype),
            data=formatted.data,
            timestamp=time.time(),
            reset_ui_object_ids=self._replacement_resets(consumer_id, selector),
        )
        self._track_ui_elements(consumer_id, selector, output.data)
        return output, None

    def _release_many(
        self,
        requested: Iterable[tuple[str, str]],
        *,
        retry_retained: bool = False,
    ) -> None:
        from marimo._types.ids import CellId_t

        released = set(requested)
        cleanup = released.union(self._retained if retry_retained else ())
        if not cleanup:
            return
        candidates = {
            identity: set(self._retained_ui.get(identity, ())) for identity in cleanup
        }
        registry = self._context.ui_element_registry
        released_references: dict[tuple[str, str], dict[str, Any]] = {}
        for identity in released:
            consumer_id, selector = identity
            referenced = self._ui_owners.pop(identity, set())
            owner = CellId_t(_owner_id(*identity))
            released_references[identity] = {
                object_id: registry._objects.get(object_id)
                for object_id in referenced
                if registry._constructing_cells.get(object_id) == owner
                or object_id.startswith(f"{owner}-")
            }
            candidates.setdefault(identity, set()).update(referenced)
            active = self._active.get(consumer_id)
            if active is not None:
                active.discard(selector)
                if not active:
                    self._active.pop(consumer_id, None)

        if candidates:
            owners = {
                identity: CellId_t(_owner_id(*identity)) for identity in candidates
            }
            retained = self._release_ui_elements(owners, candidates)
            lifecycle_registry = self._context.cell_lifecycle_registry
            for identity, owner in owners.items():
                retained_ui = retained.get(identity, set())
                if retained_ui:
                    self._retained_ui[identity] = retained_ui
                else:
                    self._retained_ui.pop(identity, None)
                lifecycle_registry.dispose(owner, deletion=False)
                if owner in lifecycle_registry.registry or retained_ui:
                    self._retained.add(identity)
                else:
                    self._retained.discard(identity)

        self._pending_notifications.update(released_references)

    def _replacement_resets(
        self,
        consumer_id: str,
        selector: str,
    ) -> tuple[str, ...]:
        identity = (consumer_id, selector)
        released = self._pending_notifications.pop(identity, {})
        registry = self._context.ui_element_registry
        resets: list[str] = []
        for object_id, released_reference in released.items():
            active_reference = registry._objects.get(object_id)
            released_value = (
                released_reference() if released_reference is not None else None
            )
            active_value = active_reference() if active_reference is not None else None
            if released_value is None or released_value is not active_value:
                resets.append(object_id)
            del released_value, active_value
        return tuple(sorted(resets))

    def _track_ui_elements(
        self,
        consumer_id: str,
        selector: str,
        data: str,
    ) -> None:
        registry = self._context.ui_element_registry
        referenced = {
            object_id
            for object_id in tuple(registry._objects)
            if f"object-id='{object_id}'" in data or f'object-id="{object_id}"' in data
        }
        identity = (consumer_id, selector)
        if referenced:
            self._ui_owners[identity] = referenced
        else:
            self._ui_owners.pop(identity, None)

    def _release_ui_elements(
        self,
        owners: Mapping[tuple[str, str], object],
        referenced: Mapping[tuple[str, str], set[str]],
    ) -> dict[tuple[str, str], set[str]]:
        registry = self._context.ui_element_registry
        candidates = {
            identity: set(object_ids) for identity, object_ids in referenced.items()
        }
        owner_identities = {owner: identity for identity, owner in owners.items()}
        for object_id, cell_id in tuple(registry._constructing_cells.items()):
            identity = owner_identities.get(cell_id)
            if identity is not None:
                candidates[identity].add(object_id)
        shared = set().union(*self._ui_owners.values()) if self._ui_owners else set()
        object_ids = set().union(*candidates.values()).difference(shared)
        references: list[tuple[str, Any, set[str] | None, object | None]] = []
        for object_id in object_ids:
            reference = registry._objects.get(object_id)
            value = reference() if reference is not None else None
            python_id = id(value) if value is not None else -1
            bindings = registry._bindings.get(object_id)
            constructing_cell = registry._constructing_cells.get(object_id)
            references.append((object_id, reference, bindings, constructing_cell))
            del value
            self._context.function_registry.delete(namespace=object_id)
            registry.delete(object_id, python_id)
        if object_ids:
            gc.collect()
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
                self._context.function_registry.register(
                    namespace=object_id,
                    function=function,
                )
            del value
        live = set(registry._objects)
        return {
            identity: object_ids.intersection(live)
            for identity, object_ids in candidates.items()
        }

    def _flush_notifications(self) -> None:
        if not self._pending_notifications:
            return

        from marimo._messaging.notification import RemoveUIElementsNotification
        from marimo._messaging.notification_utils import broadcast_notification
        from marimo._types.ids import CellId_t

        registry = self._context.ui_element_registry
        for identity, released in tuple(self._pending_notifications.items()):
            owner = CellId_t(_owner_id(*identity))
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
            broadcast_notification(RemoveUIElementsNotification(cell_id=owner))
            self._pending_notifications.pop(identity, None)
