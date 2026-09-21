from __future__ import annotations

import json
from collections.abc import MutableMapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._server.presentation.capability import (
    PresentationCapability,
    parse_presentation_capability,
)
from marimo_studio._workspace.metadata import update_notebook_config

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..app_helpers import session_manager as _session_manager
from .app_test_support import (
    _artifact_base,
    _editor_mount_value,
    _live_test_session,
    _presentation_frame_url,
    _view_support_url,
)


def _live_session_with_query(
    notebook: Path,
    query: dict[str, str | list[str]],
) -> object:
    session = _live_test_session(
        (),
        initialization_id=str(notebook),
        path=str(notebook),
    )
    cast(Any, session)._kernel_manager = SimpleNamespace(
        app_metadata=SimpleNamespace(query_params=query)
    )
    return session


def _set_query_parameter(url: str, key: str, value: str | None) -> str:
    parts = urlsplit(url)
    query = [
        (candidate, item)
        for candidate, item in parse_qsl(parts.query, keep_blank_values=True)
        if candidate != key
    ]
    if value is not None:
        query.append((key, value))
    return urlunsplit((*parts[:3], urlencode(query), parts.fragment))


def _wrapper_fallback_url(document: str) -> str:
    marker = "const config = Object.freeze("
    start = document.index(marker) + len(marker)
    config, _end = json.JSONDecoder().raw_decode(document, start)
    return cast(dict[str, str], config)["fallbackUrl"]


def _set_session_preservation(notebook: Path, enabled: bool) -> None:
    def update(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = enabled

    update_notebook_config(notebook, update)


def test_document_renewal_cannot_rebind_its_native_runtime_session(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook)
    _edit_mode(app)
    live_session = _live_test_session(())
    _session_manager(app).get_session_by_file_key = lambda _file_key: live_session
    with TestClient(app) as client:
        shell = client.get("/dashboard/")
        frame_url = _presentation_frame_url(shell.text)
        assigned_runtime_session = parse_qs(urlsplit(frame_url).query)["session_id"][0]
        presentation = client.get(frame_url)
        presentation_session = _editor_mount_value(presentation.text, "sessionId")
        config_url = _view_support_url(
            {"supportUrl": _editor_mount_value(presentation.text, "supportUrl")},
            "config",
        )
        accepted = client.get(
            config_url,
            headers={
                "Marimo-Session-Id": assigned_runtime_session,
                "Marimo-Studio-Preview-Session-Id": presentation_session,
            },
        )
        replayed = client.get(
            config_url,
            headers={
                "Marimo-Session-Id": "s_other2",
                "Marimo-Studio-Preview-Session-Id": presentation_session,
            },
        )

    assert accepted.status_code == 200
    assert presentation_session != assigned_runtime_session
    assert accepted.json()["runtime"]["data"]["sessionId"] == assigned_runtime_session
    assert replayed.status_code == 403
    assert replayed.json()["error"] == "presentation-capability-forbidden"


def test_document_renewal_carries_its_session_to_another_configured_view(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        dashboard = client.get("/dashboard/")
        dashboard_document = client.get(_wrapper_fallback_url(dashboard.text))
        renewal = _editor_mount_value(dashboard_document.text, "renewalToken")
        runtime_session_id = _editor_mount_value(
            dashboard_document.text,
            "runtimeSessionId",
        )
        presentation_session_id = _editor_mount_value(
            dashboard_document.text,
            "sessionId",
        )
        executive = client.get(
            f"/_marimo-studio/presentation/{renewal}/executive/",
            params={"session_id": runtime_session_id},
        )
        executive_config = client.get(
            _view_support_url(
                {"supportUrl": _editor_mount_value(executive.text, "supportUrl")},
                "config",
            ),
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": presentation_session_id,
            },
        )

    assert executive.status_code == 200
    assert executive_config.status_code == 200
    assert executive_config.json()["presentationSessionId"] == presentation_session_id
    assert _editor_mount_value(executive.text, "sessionId") == presentation_session_id
    assert "/_marimo-studio/views/executive" in _editor_mount_value(
        executive.text,
        "supportUrl",
    )


def test_run_document_replay_requires_the_session_creation_query(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    _set_session_preservation(studio.notebook, True)
    app = _marimo_app(studio.notebook)

    existing = {
        "s_exact1": _live_session_with_query(studio.notebook, {"region": "emea"}),
        "s_privat": _live_session_with_query(
            studio.notebook,
            {
                "region": "emea",
                "runtime": "wasm",
                "session_id": "s_other1",
            },
        ),
        "s_repeat": _live_session_with_query(
            studio.notebook,
            {"empty": "", "tag": ["first", "second"]},
        ),
        "s_wrong1": _live_session_with_query(studio.notebook, {"region": "emea"}),
        "s_nometa": _live_test_session(
            (),
            initialization_id=str(studio.notebook),
            path=str(studio.notebook),
        ),
    }
    _session_manager(app).get_session = lambda session_id: existing.get(str(session_id))

    def replay(
        client: TestClient,
        session_id: str,
        query: list[tuple[str, str]],
    ) -> tuple[dict[str, list[str]], PresentationCapability]:
        response = client.get(
            "/dashboard/",
            params=[
                *query,
                ("session_id", session_id),
                ("marimo_studio_resume", "1"),
            ],
            follow_redirects=False,
        )
        redirected = parse_qs(
            urlsplit(response.headers["location"]).query,
            keep_blank_values=True,
        )
        capability = parse_presentation_capability(
            redirected["marimo_studio_renewal"][0]
        )
        assert response.status_code == 307
        assert capability is not None
        return redirected, capability

    with TestClient(app) as client:
        exact = replay(client, "s_exact1", [("region", "emea")])
        private = replay(
            client,
            "s_privat",
            [
                ("runtime", "server"),
                ("region", "emea"),
                ("marimo_studio_server", "forged"),
            ],
        )
        repeated = replay(
            client,
            "s_repeat",
            [
                ("tag", "first"),
                ("empty", ""),
                ("tag", "second"),
            ],
        )
        mismatch = replay(client, "s_wrong1", [("region", "apac")])
        missing_metadata = replay(client, "s_nometa", [])
        fabricated = replay(client, "s_absent", [])

    for session_id, (query, capability) in {
        "s_exact1": exact,
        "s_privat": private,
        "s_repeat": repeated,
    }.items():
        assert query["session_id"] == [session_id]
        assert query["marimo_studio_resume"] == ["1"]
        assert capability.runtime_session_id == session_id

    for requested, (query, capability) in {
        "s_wrong1": mismatch,
        "s_nometa": missing_metadata,
        "s_absent": fabricated,
    }.items():
        assert query["session_id"] != [requested]
        assert "marimo_studio_resume" not in query
        assert capability.runtime_session_id == query["session_id"][0]

    assert private[0]["region"] == ["emea"]
    assert private[0]["runtime"] == ["server"]
    assert repeated[0]["tag"] == ["first", "second"]
    assert repeated[0]["empty"] == [""]


def test_stored_capability_replay_head_fails_closed(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    _set_session_preservation(studio.notebook, True)

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)
    app = _marimo_app(studio.notebook)
    runtime_session_id = "s_replay"
    active_session: list[object | None] = [
        _live_session_with_query(studio.notebook, {"region": "emea"})
    ]
    _session_manager(app).get_session = lambda session_id: (
        active_session[0] if str(session_id) == runtime_session_id else None
    )

    with TestClient(app) as client:
        redirect = client.get(
            "/dashboard/",
            params={
                "region": "emea",
                "session_id": runtime_session_id,
                "marimo_studio_resume": "1",
            },
            follow_redirects=False,
        )
        assert redirect.status_code == 307
        renewal_url = redirect.headers["location"]
        renewal_token = parse_qs(urlsplit(renewal_url).query)["marimo_studio_renewal"][
            0
        ]
        wrapper = client.get(
            _set_query_parameter(renewal_url, "marimo_studio_resume", None)
        )
        stored_url = _set_query_parameter(
            _wrapper_fallback_url(wrapper.text),
            "marimo_studio_resume",
            "1",
        )

        valid = client.head(stored_url)
        loaded = client.get(stored_url)
        wasm_replay = client.get(_set_query_parameter(stored_url, "runtime", "wasm"))
        mismatch = client.head(_set_query_parameter(stored_url, "region", "apac"))
        replacement = "0" if renewal_token[-1] != "0" else "1"
        tampered = client.head(
            stored_url.replace(renewal_token, renewal_token[:-1] + replacement)
        )
        _set_session_preservation(studio.notebook, False)
        disabled = client.head(stored_url)
        _set_session_preservation(studio.notebook, True)
        restored = client.head(stored_url)
        active_session[0] = None
        closed = client.head(stored_url)

    assert wrapper.status_code == 200
    assert valid.status_code == 200, stored_url
    assert loaded.status_code == 200
    assert _editor_mount_value(loaded.text, "replay") is True
    assert _editor_mount_value(loaded.text, "runtimeSessionId") == runtime_session_id
    assert "clientId" not in loaded.text
    assert "lifecycleId" not in loaded.text
    assert wasm_replay.status_code == 409
    assert wasm_replay.json()["error"] == "presentation-replay-unavailable"
    assert mismatch.status_code == 409
    assert tampered.status_code == 403
    assert disabled.status_code == 409
    assert restored.status_code == 200
    assert closed.status_code == 409


def test_signed_document_refresh_survives_token_authentication(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, token="test-token")
    _edit_mode(app)
    live_session = _live_test_session(())
    _session_manager(app).get_session_by_file_key = lambda _file_key: live_session

    with TestClient(app) as authenticated:
        established = authenticated.get(
            "/?access_token=test-token",
            follow_redirects=False,
        )
        authenticated.get(established.headers["location"], follow_redirects=False)
        shell = authenticated.get("/dashboard/")
        refresh_url = _presentation_frame_url(shell.text)

    with TestClient(app) as anonymous:
        refresh = anonymous.get(
            refresh_url,
            headers={"Accept": "application/json", "Origin": "null"},
        )

    assert refresh.status_code == 200
    assert refresh.headers["Marimo-Studio-Revision"]
    assert refresh.headers["Access-Control-Allow-Origin"] == "null"
    assert "Marimo-Studio-Revision" in refresh.headers["Access-Control-Expose-Headers"]


def test_document_renewal_replaces_obsolete_revision_authority(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    document = studio.views["dashboard"].root / "index.html"

    with TestClient(create_asgi_app(studio.notebook)) as client:
        loaded = client.get("/dashboard/")
        loaded_document = client.get(_wrapper_fallback_url(loaded.text))
        session_id = _editor_mount_value(loaded_document.text, "sessionId")
        runtime_session_id = _editor_mount_value(
            loaded_document.text,
            "runtimeSessionId",
        )
        renewal = _editor_mount_value(loaded_document.text, "renewalToken")
        support_url = _editor_mount_value(loaded_document.text, "supportUrl")
        first_config_url = _view_support_url(
            {"supportUrl": support_url},
            "config",
        )
        first = client.get(
            first_config_url,
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": session_id,
            },
        )
        first_payload = first.json()
        first_root = first_payload["runtime"]["data"]["url"]
        first_artifact = f"{_artifact_base(loaded_document.text)}index.html"
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "</body>",
                "<p>Updated presentation</p></body>",
                1,
            ),
            encoding="utf-8",
        )
        refreshed = client.get(
            f"/_marimo-studio/presentation/{renewal}/dashboard/",
            headers={"Marimo-Studio-Preview-Session-Id": session_id},
        )
        next_config_url = (
            f"/_marimo-studio/presentation/{renewal}/_marimo-studio/"
            f"views/dashboard/config?revision="
            f"{refreshed.headers['Marimo-Studio-Revision']}"
        )
        obsolete = client.get(
            first_config_url,
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": session_id,
            },
        )
        obsolete_preflight = client.options(
            _view_support_url(first_payload, "outputs"),
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Marimo-Session-Id,Content-Type",
            },
        )
        obsolete_outputs = client.post(
            _view_support_url(first_payload, "outputs"),
            headers={"Marimo-Session-Id": session_id},
            json={"revision": first_payload["revision"], "projections": []},
        )
        obsolete_runtime_asset = client.get(
            f"{first_root}_marimo-studio/assets/runtime.js"
        )
        obsolete_runtime_asset_head = client.head(
            f"{first_root}_marimo-studio/assets/runtime.js"
        )
        obsolete_artifact = client.get(first_artifact)
        obsolete_mutation = client.post(
            f"{first_root}api/kernel/function_call",
            headers={"Marimo-Session-Id": session_id},
            json={},
        )
        current = client.get(
            next_config_url,
            headers={
                "Marimo-Session-Id": runtime_session_id,
                "Marimo-Studio-Preview-Session-Id": session_id,
            },
        )

    assert first.status_code == 200
    assert refreshed.status_code == 200
    assert refreshed.headers["Marimo-Studio-Revision"] != first.json()["revision"]
    assert obsolete.status_code == 403
    assert obsolete.json()["error"] == "presentation-capability-forbidden"
    assert obsolete_preflight.status_code == 204
    assert obsolete_preflight.headers["Access-Control-Allow-Origin"] == "null"
    assert obsolete_outputs.status_code == 409
    assert obsolete_outputs.json()["error"] == "stale-projection-binding"
    assert obsolete_outputs.json()["transient"] is True
    assert obsolete_runtime_asset.status_code == 200
    assert obsolete_runtime_asset_head.status_code == 200
    assert obsolete_artifact.status_code == 200
    assert obsolete_mutation.status_code == 403
    assert current.status_code == 200
    assert current.json()["revision"] == refreshed.headers["Marimo-Studio-Revision"]
    assert current.json()["runtime"]["data"]["sessionId"] == runtime_session_id
