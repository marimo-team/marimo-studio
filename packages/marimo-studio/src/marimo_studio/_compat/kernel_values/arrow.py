"""Encode eager dataframes with the same Arrow stream in both Python runtimes."""

from __future__ import annotations


class _ArrowMaterializationRequired(ValueError):
    pass


class _ArrowValueTooLarge(ValueError):
    pass


def _dataframe_ipc(value: object, max_bytes: int) -> bytes | None:
    """Return an uncompressed Arrow stream or None for a non-tabular value.

    Raises ``_ArrowValueTooLarge`` once the stream passes ``max_bytes`` and
    keeps at most ``max_bytes`` of encoded output. The browser notebook embeds
    this function and its errors directly. Keep runtime dependencies inside
    the function.
    """
    import io
    import sys
    from typing import Any, cast

    from marimo._plugins.ui._impl.tables.utils import get_table_manager_or_none

    # Collect stream chunks and join them once. On macOS, a growing
    # io.BytesIO kept each large value's buffer resident in the kernel.
    class Chunks(io.RawIOBase):
        def __init__(self) -> None:
            self.parts: list[bytes] = []
            self.size = 0

        def writable(self) -> bool:
            return True

        def write(self, data: Any) -> int:
            size = memoryview(data).nbytes
            self.size += size
            if self.size > max_bytes:
                raise _ArrowValueTooLarge
            self.parts.append(bytes(data))
            return size

    def collect(write: Any) -> bytes:
        output = Chunks()
        try:
            write(output)
        except Exception:
            # Polars wraps writer errors, so the byte count decides.
            if output.size > max_bytes:
                raise _ArrowValueTooLarge from None
            raise
        return b"".join(output.parts)

    def write_stream(table: Any, pyarrow: Any) -> bytes:
        def write(output: Chunks) -> None:
            options = pyarrow.ipc.IpcWriteOptions(compression=None)
            with pyarrow.ipc.new_stream(
                output, table.schema, options=options
            ) as writer:
                writer.write_table(table)

        return collect(write)

    manager = get_table_manager_or_none(value)
    if manager is not None and manager.type in {"pandas", "polars"}:
        if manager.get_num_rows(force=False) is None:
            raise _ArrowMaterializationRequired
        if manager.type == "polars":
            dataframe = cast(Any, value)
            if any(dtype.is_object() for dtype in dataframe.schema.values()):
                raise TypeError(
                    "Polars Object columns cannot be serialized as Arrow IPC"
                )
            return collect(
                lambda output: dataframe.write_ipc_stream(
                    output, compression="uncompressed"
                )
            )
        import pyarrow

        try:
            table = pyarrow.Table.from_pandas(value)
        except Exception:
            source = pyarrow.ipc.open_file(manager.to_arrow_ipc()).read_all()
            return write_stream(source, pyarrow)
        return write_stream(table, pyarrow)

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
    return write_stream(value, pyarrow)
