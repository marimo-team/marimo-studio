"""Serve files below an explicit browser asset root."""

import asyncio
import mimetypes
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.responses import FileResponse, Response, StreamingResponse

from marimo_studio._artifacts.paths import normalized_artifact_path
from marimo_studio._artifacts.retention import ArtifactLease, LeasedArtifactFile
from marimo_studio.errors import ConfigurationError
from marimo_studio.errors._internal import ArtifactIntegrityError


class ResponseOwnerTask(BackgroundTask):
    """Release a response's file owner after delivery or on any send exit."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release
        super().__init__(release)

    def close(self) -> None:
        self._release()


def _file_response(root: Path, relative: str) -> Response:
    root = root.resolve()
    unresolved = root / relative
    try:
        unresolved.relative_to(root)
        current = unresolved
        while current != root:
            if current.is_symlink():
                return Response(status_code=404)
            current = current.parent
        candidate = unresolved.resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return Response(status_code=404)
    if not candidate.is_file():
        return Response(status_code=404)
    media_type = "text/javascript" if candidate.suffix.lower() == ".js" else None
    return FileResponse(
        candidate,
        headers={"Cache-Control": "no-cache"},
        media_type=media_type,
    )


async def file_response(root: Path, relative: str) -> Response:
    """Resolve one browser asset outside the event loop."""
    return await asyncio.to_thread(_file_response, root, relative)


def artifact_file_response(
    lease: ArtifactLease,
    relative: str,
    *,
    head: bool = False,
    if_none_match: str | None = None,
) -> Response:
    """Serve one file explicitly enumerated by a verified artifact manifest."""
    opened: LeasedArtifactFile | None = None
    try:
        path = normalized_artifact_path(relative, "Artifact request path")
        opened = lease.open_file(path)
        media_type = (
            "text/javascript"
            if path.suffix.lower() == ".js"
            else mimetypes.guess_type(path.name)[0]
        )
        etag = f'"sha256:{opened.sha256}"'
        headers = {
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Length": str(opened.size),
            "ETag": etag,
        }
        validators = (
            {item.strip() for item in if_none_match.split(",")}
            if if_none_match is not None
            else set()
        )
        if "*" in validators or etag in validators or f"W/{etag}" in validators:
            return Response(
                status_code=304,
                headers=headers,
                background=ResponseOwnerTask(opened.close),
            )
        if head:
            return Response(
                content=b"",
                headers=headers,
                media_type=media_type,
                background=ResponseOwnerTask(opened.close),
            )
        return StreamingResponse(
            opened.iter_bytes(),
            headers=headers,
            media_type=media_type,
            background=ResponseOwnerTask(opened.close),
        )
    except ArtifactIntegrityError as error:
        with suppress(OSError, ConfigurationError):
            lease.record_corruption(error)
        lease.close()
        return Response(status_code=404)
    except ConfigurationError:
        lease.close()
        return Response(status_code=404)
    except BaseException:
        if opened is None:
            lease.close()
        else:
            opened.close()
        raise


def close_artifact_response(response: Response) -> None:
    """Release the artifact owner transferred into one response."""
    background = response.background
    if isinstance(background, ResponseOwnerTask):
        background.close()
