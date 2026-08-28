"""Encode selected kernel values for the browser runtime."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from marimo._plugins.ui._impl.tables.utils import get_table_manager_or_none
from marimo._runtime.virtual_file import VirtualFile, random_filename

from marimo_studio._projections.runtime_records import ValueReadError

JSON_CODEC = "json-v1"
ARROW_IPC_CODEC = "arrow-ipc-v1"


class _ArrowMaterializationRequired(ValueError):
    pass


@dataclass(frozen=True)
class EncodedValue:
    payload: dict[str, object]
    byte_length: int
    resource: VirtualFile | None = None
    resource_key: tuple[str, str, str] | None = None
    reused_resource: bool = False


def _fingerprint(data: bytes) -> str:
    return f"sha256:{sha256(data).hexdigest()}"


def inspection_value(payload: object) -> object:
    """Return the stable runtime-inspection view of one encoded value."""
    if not isinstance(payload, dict):
        return payload
    if payload.get("codec") == JSON_CODEC:
        return payload.get("value")
    if payload.get("codec") == ARROW_IPC_CODEC:
        return {
            "codec": ARROW_IPC_CODEC,
            "fingerprint": payload.get("fingerprint"),
            "byteLength": payload.get("byteLength"),
        }
    return payload


def _write_arrow_stream(table: Any, pyarrow: Any) -> bytes:
    output = io.BytesIO()
    options = pyarrow.ipc.IpcWriteOptions(compression=None)
    with pyarrow.ipc.new_stream(output, table.schema, options=options) as writer:
        writer.write_table(table)
    return output.getvalue()


def _pyarrow_ipc(value: object) -> bytes | None:
    pyarrow = sys.modules.get("pyarrow")
    if pyarrow is None:
        return None
    table_type = getattr(pyarrow, "Table", ())
    batch_type = getattr(pyarrow, "RecordBatch", ())
    if isinstance(value, batch_type):
        batch: Any = value
        value = pyarrow.Table.from_batches([batch], schema=batch.schema)
    if not isinstance(value, table_type):
        return None
    table: Any = value
    return _write_arrow_stream(table, pyarrow)


def _dataframe_ipc(value: object) -> bytes | None:
    manager = get_table_manager_or_none(value)
    if manager is None or manager.type not in {"pandas", "polars"}:
        return _pyarrow_ipc(value)
    if manager.get_num_rows(force=False) is None:
        raise _ArrowMaterializationRequired
    if manager.type == "polars":
        dataframe: Any = value
        if any(dtype.is_object() for dtype in dataframe.schema.values()):
            raise TypeError("Polars Object columns cannot be serialized as Arrow IPC")
        output = io.BytesIO()
        dataframe.write_ipc_stream(output, compression="uncompressed")
        return output.getvalue()
    import pyarrow

    try:
        table = pyarrow.Table.from_pandas(value)
    except Exception:
        source = pyarrow.ipc.open_file(io.BytesIO(manager.to_arrow_ipc())).read_all()
        return _write_arrow_stream(source, pyarrow)
    return _write_arrow_stream(table, pyarrow)


class ValueEncoder:
    """Encode values and own the virtual files backing Arrow payloads."""

    def __init__(self, context: Any | None = None) -> None:
        self._context = context
        self._resources: dict[tuple[str, str, str], tuple[str, VirtualFile]] = {}

    def prepare(
        self,
        value: object,
        *,
        consumer_id: str,
        revision: str,
        selector: str,
        max_value_bytes: int,
    ) -> tuple[EncodedValue | None, ValueReadError | None]:
        try:
            ipc = _dataframe_ipc(value)
        except _ArrowMaterializationRequired:
            return None, ValueReadError(
                "arrow-materialization-required",
                f"Materialize selector {selector!r} before projecting it.",
            )
        except (ImportError, ModuleNotFoundError) as error:
            return None, ValueReadError(
                "arrow-codec-unavailable",
                f"Selector {selector!r} requires PyArrow for Arrow IPC: {error}",
            )
        except Exception as error:
            return None, ValueReadError(
                "arrow-serialization-error",
                f"Selector {selector!r} could not be serialized as Arrow IPC: {error}",
            )
        if ipc is not None:
            return self._prepare_arrow(
                ipc,
                consumer_id=consumer_id,
                revision=revision,
                selector=selector,
                max_value_bytes=max_value_bytes,
            )
        return self._prepare_json(
            value,
            selector=selector,
            max_value_bytes=max_value_bytes,
        )

    def _prepare_json(
        self,
        value: object,
        *,
        selector: str,
        max_value_bytes: int,
    ) -> tuple[EncodedValue | None, ValueReadError | None]:
        try:
            text = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            return None, ValueReadError(
                "not-json-serializable",
                (
                    f"Selector {selector!r} resolved to {type(value).__name__}, "
                    f"which cannot be serialized as JSON: {error}"
                ),
            )
        encoded = text.encode("utf-8")
        if len(encoded) > max_value_bytes:
            return None, ValueReadError(
                "value-too-large",
                f"Selector {selector!r} exceeds the {max_value_bytes}-byte limit.",
            )
        return (
            EncodedValue(
                payload={
                    "codec": JSON_CODEC,
                    "fingerprint": _fingerprint(encoded),
                    "value": json.loads(text),
                },
                byte_length=len(encoded),
            ),
            None,
        )

    def _prepare_arrow(
        self,
        ipc: bytes,
        *,
        consumer_id: str,
        revision: str,
        selector: str,
        max_value_bytes: int,
    ) -> tuple[EncodedValue | None, ValueReadError | None]:
        size = len(ipc)
        if size > max_value_bytes:
            return None, ValueReadError(
                "value-too-large",
                f"Selector {selector!r} exceeds the {max_value_bytes}-byte limit.",
            )
        fingerprint = _fingerprint(ipc)
        key = (consumer_id, revision, selector)
        current = self._resources.get(key)
        if current is not None and current[0] == fingerprint:
            resource = current[1]
            reused = True
        else:
            resource = (
                VirtualFile.create_and_register(ipc, "arrow")
                if self._context is not None
                else VirtualFile(
                    random_filename("arrow"),
                    ipc,
                    as_data_url=True,
                )
            )
            reused = False
        return (
            EncodedValue(
                payload={
                    "codec": ARROW_IPC_CODEC,
                    "fingerprint": fingerprint,
                    "dataUrl": resource.url,
                    "byteLength": size,
                },
                byte_length=size,
                resource=resource,
                resource_key=key,
                reused_resource=reused,
            ),
            None,
        )

    def commit(self, encoded: EncodedValue) -> None:
        key = encoded.resource_key
        if key is None:
            return
        resource = encoded.resource
        assert resource is not None
        previous = self._resources.get(key)
        if previous is not None and previous[1] is not resource:
            try:
                self._release(previous[1])
            except BaseException:
                if not encoded.reused_resource:
                    self._release(resource)
                raise
        self._resources[key] = (str(encoded.payload["fingerprint"]), resource)

    def discard(self, encoded: EncodedValue) -> None:
        if encoded.resource is not None and not encoded.reused_resource:
            self._release(encoded.resource)

    def release_selector(
        self,
        *,
        consumer_id: str,
        revision: str,
        selector: str,
    ) -> None:
        key = (consumer_id, revision, selector)
        previous = self._resources.get(key)
        if previous is not None:
            self._release(previous[1])
            del self._resources[key]

    def release_inactive(
        self,
        *,
        consumer_id: str,
        revision: str,
        active_selectors: set[str],
    ) -> None:
        self._release_matching(
            lambda key: (
                key[0] == consumer_id
                and key[1] == revision
                and key[2] not in active_selectors
            )
        )

    def release_other_revisions(self, consumer_id: str, revision: str) -> None:
        self._release_matching(lambda key: key[0] == consumer_id and key[1] != revision)

    def release_consumer(self, consumer_id: str) -> None:
        self._release_matching(lambda key: key[0] == consumer_id)

    def close(self) -> None:
        self._release_matching(lambda _key: True)

    def _release_matching(
        self,
        matches: Callable[[tuple[str, str, str]], bool],
    ) -> None:
        for key in tuple(self._resources):
            if matches(key):
                _fingerprint_value, resource = self._resources[key]
                self._release(resource)
                del self._resources[key]

    def _release(self, resource: VirtualFile) -> None:
        if resource.url.startswith("data:") or self._context is None:
            return
        self._context.virtual_file_registry.remove(resource)
