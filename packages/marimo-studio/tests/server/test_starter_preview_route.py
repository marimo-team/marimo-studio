from __future__ import annotations

import hashlib
from pathlib import Path

from starlette.testclient import TestClient

from marimo_studio import create_asgi_app

from ..app_helpers import configured as _configured

PREVIEW = "/_marimo-studio/starters/preview"


def test_starter_preview_serves_the_image_its_catalog_record_names(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        inventory = client.get("/_marimo-studio/views").json()
        typst = next(
            item
            for item in inventory["starters"]
            if item["id"] == "marimo-studio/typst:default"
        )
        current = client.get(
            PREVIEW, params={"starter": typst["id"], "revision": typst["preview"]}
        )
        unpinned = client.get(PREVIEW, params={"starter": typst["id"]})

    assert current.status_code == 200
    assert current.headers["content-type"] == "image/webp"
    assert hashlib.sha256(current.content).hexdigest() == typst["preview"]
    assert "immutable" in current.headers["cache-control"]
    assert current.headers["x-content-type-options"] == "nosniff"
    assert current.headers["content-security-policy"] == "default-src 'none'"
    assert unpinned.content == current.content
    assert unpinned.headers["cache-control"] == "no-cache"


def test_starter_preview_is_missing_for_unknown_starters_and_providers(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        responses = [
            client.get(PREVIEW, params={"starter": starter})
            for starter in (
                "marimo-studio/typst:missing",
                "acme-views/missing:default",
                "not-a-starter",
            )
        ]
        bare = client.get(PREVIEW)

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert bare.status_code == 404
