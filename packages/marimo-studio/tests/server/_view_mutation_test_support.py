from __future__ import annotations

from typing import cast

from starlette.testclient import TestClient


def _create_owned_view(
    client: TestClient,
    name: str,
    headers: dict[str, str],
    generation: str | None = None,
):
    owner = generation or cast(
        str, client.get("/_marimo-studio/views").json()["generation"]
    )
    return client.post(
        "/_marimo-studio/views",
        headers=headers,
        json={
            "catalog_generation": owner,
            "name": name,
            "starter": "marimo-studio/vanilla:default",
        },
    )


def _view_owner(client: TestClient, name: str) -> tuple[str, str]:
    inventory = client.get("/_marimo-studio/views").json()
    view = next(item for item in inventory["views"] if item["name"] == name)
    return cast(str, inventory["generation"]), cast(str, view["generation"])
