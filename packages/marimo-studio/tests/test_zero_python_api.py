from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from marimo_export.errors import IntegrityError
from marimo_export.manifest import PreparedManifestLimitError
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.prepared_views import PreparedViewRegistry
from marimo_studio._server.zero_python_api import (
    zero_python_response as _zero_python_response,
)
from marimo_studio.errors import PublicationError, PublicationLimitError

_REVISION = "a" * 64


class _Clients:
    async def session_for_client(self, client_id: str) -> str | None:
        return {
            "browser-client-1234": "s_abcdef",
            "browser-client-first": "s_abcdef",
            "browser-client-second": "s_ghijkl",
        }.get(client_id)


def zero_python_response(*args: Any, **kwargs: Any) -> Response:
    kwargs.setdefault("clients", cast(StudioClientRegistry, _Clients()))
    return asyncio.run(_zero_python_response(*args, **kwargs))


class _PreparedView:
    def __init__(self, instance: str, current: int) -> None:
        self.instance = instance
        self.current = current
        self.plan_digest = "b" * 64

    def manifest(
        self,
        export_url: str,
        *,
        refresh_interval_ms: int = 1000,
    ) -> dict[str, object]:
        return {
            "schema": "marimo-studio.prepared.v1",
            "prepared": {
                "schema": "marimo-export.prepared.v1",
                "instance": self.instance,
                "export_url": export_url,
                "inputs": {"scale": self.current},
                "state_fingerprint": "c" * 64,
                "refresh_interval_ms": refresh_interval_ms,
            },
            "projections": {"cells": {}, "outputs": {}, "values": {}},
            "document_sha256": "d" * 64,
            "view": "dashboard",
            "plan_digest": self.plan_digest,
        }


class _LargePreparedView(_PreparedView):
    def manifest(
        self,
        export_url: str,
        *,
        refresh_interval_ms: int = 1000,
    ) -> dict[str, object]:
        manifest = super().manifest(
            export_url,
            refresh_interval_ms=refresh_interval_ms,
        )
        manifest["projections"] = {
            "cells": {},
            "outputs": {},
            "values": {
                f"host-{index}-{'h' * 900}": f"value:{index}-{'o' * 240}"
                for index in range(300)
            },
        }
        return manifest


class _FailingPreparedView(_PreparedView):
    def __init__(self, instance: str, current: int, failure: Exception) -> None:
        super().__init__(instance, current)
        self.failure = failure

    def manifest(
        self,
        export_url: str,
        *,
        refresh_interval_ms: int = 1000,
    ) -> dict[str, object]:
        del export_url, refresh_interval_ms
        raise self.failure


class _PreparedAsset:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Publications:
    def __init__(
        self,
        *,
        current: _PreparedView | None = None,
        polled: _PreparedView | None = None,
        assets: dict[tuple[str, str], Path] | None = None,
    ) -> None:
        self.selected = current
        self.polled = polled
        self.asset_paths = assets or {}
        self.current_calls: list[tuple[str, str, str]] = []
        self.poll_calls: list[tuple[str, str, str]] = []
        self.asset_calls: list[tuple[str, str, str]] = []
        self.borrowed: list[_PreparedAsset] = []

    def current(
        self,
        view: str,
        binding_id: str,
        revision: str,
    ) -> _PreparedView | None:
        self.current_calls.append((view, binding_id, revision))
        return self.selected

    def poll_current(
        self,
        view: str,
        binding_id: str,
        revision: str,
    ) -> _PreparedView | None:
        self.poll_calls.append((view, binding_id, revision))
        return self.polled

    async def publication_asset(
        self,
        view: str,
        instance: str,
        relative: str,
    ) -> _PreparedAsset | None:
        self.asset_calls.append((view, instance, relative))
        path = self.asset_paths.get((instance, relative))
        if path is None:
            return None
        asset = _PreparedAsset(path)
        self.borrowed.append(asset)
        return asset


def _request(
    path: str,
    method: str = "GET",
    query: str = (
        "file=analysis.py&marimo_studio_client=browser-client-1234&"
        f"revision={_REVISION}"
    ),
) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
        }
    )


def _export_files(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    index = root / "index.json"
    index.write_text("{}", encoding="utf-8")
    assets = root / "assets"
    assets.mkdir()
    value = assets / "value.bin"
    value.write_bytes(b"value")
    return index, value


def _registry(publications: _Publications) -> PreparedViewRegistry:
    return cast(PreparedViewRegistry, publications)


def test_current_manifest_is_no_store_and_points_at_immutable_export() -> None:
    selected = _PreparedView("1" * 64, 2)
    publications = _Publications(current=selected)

    response = zero_python_response(
        _request("/parent/base/_marimo-studio/views/dashboard/zero-python/current"),
        _registry(publications),
        "dashboard",
        "current",
        allow_refresh=False,
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.body is not None
    manifest = json.loads(bytes(response.body))
    prepared = manifest["prepared"]
    assert prepared["instance"] == "1" * 64
    assert prepared["export_url"] == (
        "http://testserver/parent/base/_marimo-studio/views/dashboard/"
        f"zero-python/{'1' * 64}/?file=analysis.py"
    )
    assert publications.current_calls == [("dashboard", "s_abcdef", _REVISION)]


def test_current_manifest_rejects_three_hundred_large_hosts() -> None:
    publications = _Publications(current=_LargePreparedView("1" * 64, 2))

    with pytest.raises(PublicationLimitError, match="262144-byte limit"):
        zero_python_response(
            _request("/_marimo-studio/views/dashboard/zero-python/current"),
            _registry(publications),
            "dashboard",
            "current",
            allow_refresh=False,
        )


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (IntegrityError("prepared export changed"), PublicationError),
        (
            PreparedManifestLimitError("prepared manifest is too large"),
            PublicationLimitError,
        ),
    ),
)
def test_current_manifest_translates_public_export_failures(
    failure: Exception,
    expected: type[PublicationError],
) -> None:
    selected = _FailingPreparedView("1" * 64, 2, failure)
    publications = _Publications(current=selected)

    with pytest.raises(expected, match=str(failure)):
        zero_python_response(
            _request("/_marimo-studio/views/dashboard/zero-python/current"),
            _registry(publications),
            "dashboard",
            "current",
            allow_refresh=False,
        )


def test_immutable_export_url_is_shared_across_clients_and_revisions(
    tmp_path: Path,
) -> None:
    selected = _PreparedView("1" * 64, 2)
    index, _value = _export_files(tmp_path / "generation")
    publications = _Publications(
        current=selected,
        assets={(selected.instance, "index.json"): index},
    )

    manifests = []
    for client_id, revision in (
        ("browser-client-first", "a" * 64),
        ("browser-client-second", "b" * 64),
    ):
        response = zero_python_response(
            _request(
                "/parent/base/_marimo-studio/views/dashboard/zero-python/current",
                query=(
                    "file=nested%2Fanalysis.py&region=emea&region=apac&empty=&"
                    f"marimo_studio_client={client_id}&revision={revision}"
                ),
            ),
            _registry(publications),
            "dashboard",
            "current",
            allow_refresh=False,
        )
        assert response.headers["cache-control"] == "no-store"
        assert response.body is not None
        manifests.append(json.loads(bytes(response.body)))

    expected = (
        "http://testserver/parent/base/_marimo-studio/views/dashboard/"
        f"zero-python/{selected.instance}/?"
        "file=nested%2Fanalysis.py&region=emea&region=apac&empty="
    )
    assert [manifest["prepared"]["export_url"] for manifest in manifests] == [
        expected,
        expected,
    ]
    immutable = zero_python_response(
        _request(
            f"/_marimo-studio/views/dashboard/zero-python/"
            f"{selected.instance}/index.json"
        ),
        _registry(publications),
        "dashboard",
        f"{selected.instance}/index.json",
        allow_refresh=False,
    )
    assert immutable.headers["cache-control"] == (
        "private, max-age=31536000, immutable"
    )
    assert publications.asset_calls == [("dashboard", selected.instance, "index.json")]
    assert immutable.background is not None
    asyncio.run(immutable.background())
    assert publications.borrowed[0].closed


def test_borrowed_export_assets_remain_open_until_responses_finish(
    tmp_path: Path,
) -> None:
    first = _PreparedView("1" * 64, 1)
    second = _PreparedView("2" * 64, 2)
    first_index, _first_value = _export_files(tmp_path / "first")
    _second_index, second_value = _export_files(tmp_path / "second")
    publications = _Publications(
        assets={
            (first.instance, "index.json"): first_index,
            (second.instance, "assets/value.bin"): second_value,
        }
    )

    old = zero_python_response(
        _request(
            f"/_marimo-studio/views/dashboard/zero-python/{first.instance}/index.json"
        ),
        _registry(publications),
        "dashboard",
        f"{first.instance}/index.json",
        allow_refresh=False,
    )
    newest = zero_python_response(
        _request(
            f"/_marimo-studio/views/dashboard/zero-python/"
            f"{second.instance}/assets/value.bin"
        ),
        _registry(publications),
        "dashboard",
        f"{second.instance}/assets/value.bin",
        allow_refresh=False,
    )

    assert isinstance(old, FileResponse)
    assert isinstance(newest, FileResponse)
    assert publications.asset_calls == [
        ("dashboard", first.instance, "index.json"),
        ("dashboard", second.instance, "assets/value.bin"),
    ]
    assert [asset.closed for asset in publications.borrowed] == [False, False]
    assert old.background is not None
    assert newest.background is not None
    asyncio.run(old.background())
    asyncio.run(newest.background())
    assert [asset.closed for asset in publications.borrowed] == [True, True]


def test_export_route_rejects_traversal_and_unpublished_paths() -> None:
    instance = "1" * 64
    publications = _Publications()

    for relative in (
        f"{instance}/../index.json",
        f"{instance}/assets/../../secret",
    ):
        response = zero_python_response(
            _request(f"/_marimo-studio/views/dashboard/zero-python/{relative}"),
            _registry(publications),
            "dashboard",
            relative,
            allow_refresh=False,
        )
        assert response.status_code == 404

    assert publications.asset_calls == []


def test_missing_asset_path_releases_the_prepared_asset(tmp_path: Path) -> None:
    instance = "1" * 64
    publications = _Publications(
        assets={(instance, "assets/missing.bin"): tmp_path / "missing.bin"}
    )

    response = zero_python_response(
        _request(
            f"/_marimo-studio/views/dashboard/zero-python/{instance}/assets/missing.bin"
        ),
        _registry(publications),
        "dashboard",
        f"{instance}/assets/missing.bin",
        allow_refresh=False,
    )

    assert response.status_code == 404
    assert publications.borrowed[0].closed


def test_current_manifest_requires_valid_browser_binding() -> None:
    selected = _PreparedView("1" * 64, 1)
    publications = _Publications(current=selected)

    missing = zero_python_response(
        _request(
            "/_marimo-studio/views/dashboard/zero-python/current",
            query="file=analysis.py",
        ),
        _registry(publications),
        "dashboard",
        "current",
        allow_refresh=False,
    )
    invalid = zero_python_response(
        _request(
            "/_marimo-studio/views/dashboard/zero-python/current",
            query="marimo_studio_client=short",
        ),
        _registry(publications),
        "dashboard",
        "current",
        allow_refresh=False,
    )

    assert missing.status_code == 409
    assert missing.body is not None
    assert b"zero-python-publication-unavailable" in missing.body
    assert invalid.status_code == 400
    assert invalid.body is not None
    assert b"invalid-browser-client" in invalid.body
    assert publications.current_calls == []


def test_current_manifest_requires_exact_presentation_revision() -> None:
    selected = _PreparedView("1" * 64, 1)
    publications = _Publications(current=selected)
    path = "/_marimo-studio/views/dashboard/zero-python/current"

    missing = zero_python_response(
        _request(path, query="marimo_studio_client=browser-client-1234"),
        _registry(publications),
        "dashboard",
        "current",
        allow_refresh=False,
    )
    malformed = zero_python_response(
        _request(
            path,
            query="marimo_studio_client=browser-client-1234&revision=stale",
        ),
        _registry(publications),
        "dashboard",
        "current",
        allow_refresh=False,
    )

    assert missing.status_code == 400
    assert missing.body is not None
    assert b"invalid-presentation-revision" in missing.body
    assert malformed.status_code == 400
    assert malformed.body is not None
    assert b"invalid-presentation-revision" in malformed.body
    assert publications.current_calls == []


def test_edit_manifest_poll_uses_refreshing_selection() -> None:
    selected = _PreparedView("1" * 64, 1)
    publications = _Publications(polled=selected)

    response = zero_python_response(
        _request("/_marimo-studio/views/dashboard/zero-python/current"),
        _registry(publications),
        "dashboard",
        "current",
        allow_refresh=True,
    )

    assert response.status_code == 200
    assert publications.poll_calls == [("dashboard", "s_abcdef", _REVISION)]
    assert publications.current_calls == []
