"""Publish an E2E backend's already-bound socket to its process owner."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


def publish_endpoint(port: int) -> None:
    destination = Path(os.environ["MARIMO_STUDIO_E2E_ENDPOINT_FILE"])
    owner = os.environ["MARIMO_STUDIO_E2E_PROCESS_OWNER"]
    if not destination.is_absolute() or re.fullmatch(r"[a-f0-9]{64}", owner) is None:
        raise ValueError(
            "E2E endpoint requires an absolute receipt path and owner nonce"
        )
    if not 0 < port <= 65535:
        raise ValueError("E2E endpoint must identify a bound TCP port")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f"{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump({"ownerNonce": owner, "pid": os.getpid(), "port": port}, output)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
