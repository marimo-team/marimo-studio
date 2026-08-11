"""Serve files below an explicit browser asset root."""

from pathlib import Path

from starlette.responses import FileResponse, Response


def file_response(root: Path, relative: str) -> Response:
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
