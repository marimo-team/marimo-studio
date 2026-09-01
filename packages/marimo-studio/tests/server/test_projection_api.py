from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from starlette.testclient import TestClient

import marimo_studio._compat.kernel_values.host as kernel_projection_host
from marimo_studio import create_asgi_app
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.records import CellRef, LiveCellSnapshot
from marimo_studio.errors._internal import RuntimeSyncError

from ..app_helpers import published_dashboard
from ..app_helpers import set_shell as _set_shell
from .app_test_support import (
    _live_test_session,
    _projection_request,
    _view_support_url,
)


def test_value_permissions_are_narrowed_by_view(notebook_path: Path) -> None:
    studio = published_dashboard(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {
            "Marimo-Session-Id": config["presentationSessionId"],
        }
        allowed_projection = _projection_request(config, "value", "doubled")
        allowed = client.post(
            _view_support_url(config, "values"),
            headers=headers,
            json={
                "revision": config["revision"],
                "projections": [allowed_projection],
                "activeProjections": [allowed_projection],
            },
        )
        cross_view_projection = _projection_request(
            config,
            "value",
            "x",
            site_target="doubled",
        )
        cross_view = client.post(
            _view_support_url(config, "values"),
            headers=headers,
            json={
                "revision": config["revision"],
                "projections": [cross_view_projection],
                "activeProjections": [cross_view_projection],
            },
        )

    assert allowed.status_code == 409
    assert allowed.json()["error"] == "unknown-session"
    assert cross_view.status_code == 400
    assert cross_view.json()["error"] == "projection-target-not-allowed"


def test_value_requests_allow_repeated_instances_with_one_target(
    notebook_path: Path,
) -> None:
    studio = published_dashboard(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        projections = [
            _projection_request(
                config,
                "value",
                "doubled",
                instance=f"value-{index}",
            )
            for index in range(101)
        ]
        response = client.post(
            _view_support_url(config, "values"),
            headers={
                "Marimo-Session-Id": config["presentationSessionId"],
            },
            json={
                "revision": config["revision"],
                "projections": projections,
                "activeProjections": projections,
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "unknown-session"


def test_output_permissions_are_narrowed_by_view(notebook_path: Path) -> None:
    studio = published_dashboard(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        headers = {
            "Marimo-Session-Id": config["presentationSessionId"],
        }
        allowed = client.post(
            _view_support_url(config, "outputs"),
            headers=headers,
            json={
                "revision": config["revision"],
                "projections": [_projection_request(config, "output", "doubled")],
                "activeProjections": [_projection_request(config, "output", "doubled")],
            },
        )
        cross_view = client.post(
            _view_support_url(config, "outputs"),
            headers=headers,
            json={
                "revision": config["revision"],
                "projections": [
                    _projection_request(
                        config,
                        "output",
                        "x",
                        site_target="doubled",
                    )
                ],
                "activeProjections": [_projection_request(config, "output", "doubled")],
            },
        )
        inactive = client.post(
            _view_support_url(config, "outputs"),
            headers=headers,
            json={
                "revision": config["revision"],
                "projections": [_projection_request(config, "output", "doubled")],
                "activeProjections": [],
            },
        )

    assert allowed.status_code == 409
    assert allowed.json()["error"] == "unknown-session"
    assert cross_view.status_code == 400
    assert cross_view.json()["error"] == "projection-target-not-allowed"
    assert inactive.status_code == 400
    assert inactive.json()["error"] == "invalid-output-request"


def test_output_requests_reject_duplicate_mounted_owners(
    notebook_path: Path,
) -> None:
    studio = published_dashboard(notebook_path)
    _set_shell(
        studio,
        "dashboard",
        '<marimo-output value="doubled"></marimo-output>'
        '<marimo-output value="doubled"></marimo-output>',
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        sites = [site for site in config["mounts"] if site["kind"] == "output"]
        active = [
            {
                "siteId": site["id"],
                "instanceId": f"output-{index}",
                "target": "doubled",
            }
            for index, site in enumerate(sites)
        ]
        response = client.post(
            _view_support_url(config, "outputs"),
            headers={
                "Marimo-Session-Id": config["presentationSessionId"],
            },
            json={
                "revision": config["revision"],
                "projections": active[:1],
                "activeProjections": active,
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "duplicate-output-owner"


@pytest.mark.parametrize(
    ("endpoint", "kind"), (("values", "value"), ("outputs", "output"))
)
def test_projection_http_rejects_padded_wildcard_targets(
    notebook_path: Path,
    endpoint: str,
    kind: str,
) -> None:
    studio = published_dashboard(notebook_path)
    tag = (
        '<span mo-value="doubled" data-marimo-allow="*"></span>'
        if kind == "value"
        else '<marimo-output value="doubled" data-marimo-allow="*"></marimo-output>'
    )
    _set_shell(studio, "dashboard", tag)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(
            config,
            kind,
            " doubled ",
            site_target="doubled",
        )
        body: dict[str, object] = {
            "projections": [projection],
            "activeProjections": [projection],
        }
        if kind == "output":
            canonical = _projection_request(
                config,
                kind,
                "doubled",
                instance="canonical-output",
            )
            body = {
                "projections": [canonical],
                "activeProjections": [canonical, projection],
            }
        response = client.post(
            _view_support_url(config, endpoint),
            headers={
                "Marimo-Session-Id": config["presentationSessionId"],
            },
            json={"revision": config["revision"], **body},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "projection-target-invalid"


def test_projection_http_rejects_unpaired_utf16_surrogates(
    notebook_path: Path,
) -> None:
    studio = published_dashboard(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(config, "value", "doubled")
        projection["target"] = "\ud800"
        response = client.post(
            _view_support_url(config, "values"),
            headers={
                "Content-Type": "application/json",
                "Marimo-Session-Id": config["presentationSessionId"],
            },
            content=json.dumps(
                {
                    "revision": config["revision"],
                    "projections": [projection],
                    "activeProjections": [projection],
                },
                ensure_ascii=True,
            ).encode("utf-8"),
        )

    assert response.status_code == 400
    assert response.json()["error"] == "projection-unpaired-surrogate"


@pytest.mark.parametrize(
    ("endpoint", "kind", "reader_name"),
    [
        ("values", "value", "read_values"),
        ("outputs", "output", "render_outputs"),
    ],
)
def test_projection_resolves_session_once(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    kind: str,
    reader_name: str,
) -> None:
    studio = published_dashboard(notebook_path)
    app = create_asgi_app(studio.notebook)
    resolved: list[str] = []
    projection_calls: list[tuple[object, ...]] = []

    async def read_projection(
        _host: object,
        _context: object,
        session_id: str,
        *_args: object,
        **_kwargs: object,
    ) -> SimpleNamespace:
        resolved.append(session_id)
        projection_calls.append(_args)
        return SimpleNamespace(errors={}, to_dict=lambda: {"errors": {}})

    monkeypatch.setattr(
        f"marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.{reader_name}",
        read_projection,
    )

    with TestClient(app) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(config, kind, "doubled")
        body: dict[str, object] = {
            "projections": [projection],
            "activeProjections": [projection],
        }
        response = client.post(
            _view_support_url(config, endpoint),
            headers={
                "Marimo-Session-Id": config["presentationSessionId"],
            },
            json={"revision": config["revision"], **body},
        )

    assert response.status_code == 200
    assert resolved == [config["runtime"]["data"]["sessionId"]]
    assert projection_calls[0][0] == config["revision"]
    requested = projection_calls[0][1]
    assert isinstance(requested, tuple)
    assert [item.request.target for item in requested] == ["doubled"]
    if kind == "output":
        active = projection_calls[0][2]
        assert isinstance(active, tuple)
        assert [item.request.target for item in active] == ["doubled"]


@pytest.mark.parametrize(
    ("endpoint", "kind", "reader_name"),
    [
        ("values", "value", "read_values"),
        ("outputs", "output", "render_outputs"),
    ],
)
def test_projection_uses_live_runtime_ids_after_a_cell_is_inserted(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    kind: str,
    reader_name: str,
) -> None:
    studio = published_dashboard(notebook_path)
    static = load_static_notebook(studio.notebook)
    references = cell_refs(cell.code for cell in static.cells)
    live_ids = {
        reference: f"live-{index}" for index, reference in enumerate(references)
    }
    live_cells = LiveCellSnapshot(
        owner="session:test",
        generation="0" * 64,
        ids=live_ids,
        names={},
        dependency_closures={
            runtime_id: (runtime_id,) for runtime_id in live_ids.values()
        },
        current_refs={
            runtime_id: reference for reference, runtime_id in live_ids.items()
        },
    )
    observed: list[dict[CellRef, str]] = []

    async def current_live_cells(*_args: object, **_kwargs: object):
        return live_cells

    monkeypatch.setattr(
        "marimo_studio._compat.server.session_state.PrivateSessionState.live_cells",
        current_live_cells,
    )

    async def read_projection(
        *_args: object,
        **options: object,
    ) -> SimpleNamespace:
        observed.append(cast(dict[CellRef, str], options["runtime_cell_refs"]))
        return SimpleNamespace(errors={}, to_dict=lambda: {"errors": {}})

    monkeypatch.setattr(
        f"marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.{reader_name}",
        read_projection,
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(config, kind, "doubled")
        body: dict[str, object] = {
            "projections": [projection],
            "activeProjections": [projection],
        }
        response = client.post(
            _view_support_url(config, endpoint),
            headers={"Marimo-Session-Id": config["presentationSessionId"]},
            json={"revision": config["revision"], **body},
        )

    assert response.status_code == 200
    assert observed == [
        {
            CellRef.parse(reference): runtime_id
            for reference, runtime_id in config["runtimeBindings"]["cellRefs"].items()
        }
    ]


@pytest.mark.parametrize(
    ("endpoint", "kind", "reader_name"),
    [
        ("values", "value", "read_values"),
        ("outputs", "output", "render_outputs"),
    ],
)
def test_projection_waits_for_the_live_session_binding(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    kind: str,
    reader_name: str,
) -> None:
    studio = published_dashboard(notebook_path)
    calls: list[object] = []

    async def read_projection(*args: object, **_options: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(errors={}, to_dict=lambda: {"errors": {}})

    monkeypatch.setattr(
        f"marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.{reader_name}",
        read_projection,
    )

    async def syncing_session(
        *_args: object,
        **_kwargs: object,
    ) -> LiveCellSnapshot:
        raise RuntimeSyncError("The live session is applying the saved notebook.")

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        monkeypatch.setattr(
            "marimo_studio._compat.server.session_state.PrivateSessionState.live_cells",
            syncing_session,
        )
        projection = _projection_request(config, kind, "doubled")
        body: dict[str, object] = {
            "projections": [projection],
            "activeProjections": [projection],
        }
        response = client.post(
            _view_support_url(config, endpoint),
            headers={"Marimo-Session-Id": config["presentationSessionId"]},
            json={"revision": config["revision"], **body},
        )

    assert response.status_code == 409
    assert response.json()["error"] == "runtime-sync-pending"
    assert response.json()["transient"] is True
    assert calls == []


@pytest.mark.parametrize(
    ("endpoint", "kind", "reader_name"),
    [
        ("values", "value", "read_values"),
        ("outputs", "output", "render_outputs"),
    ],
)
def test_projection_retries_while_the_kernel_applies_the_current_binding(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    kind: str,
    reader_name: str,
) -> None:
    studio = published_dashboard(notebook_path)

    async def read_projection(*_args: object, **_kwargs: object) -> SimpleNamespace:
        error = SimpleNamespace(
            code="stale-projection-binding",
            message="The authorized projection producer is stale.",
        )
        return SimpleNamespace(errors={"*": error}, to_dict=lambda: {"errors": {}})

    monkeypatch.setattr(
        f"marimo_studio._compat.kernel_values.host.PrivateKernelProjectionHost.{reader_name}",
        read_projection,
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(config, kind, "doubled")
        body: dict[str, object] = {
            "projections": [projection],
            "activeProjections": [projection],
        }
        response = client.post(
            _view_support_url(config, endpoint),
            headers={
                "Marimo-Session-Id": config["presentationSessionId"],
            },
            json={"revision": config["revision"], **body},
        )

    assert response.status_code == 409
    assert response.json()["error"] == "stale-projection-binding"
    assert response.json()["transient"] is True


def test_value_permissions_follow_the_browser_presentation_revision(
    notebook_path: Path,
) -> None:
    studio = published_dashboard(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/_marimo-studio/views/dashboard/config").json()
        _set_shell(studio, "dashboard", "<p>Updated dashboard</p>")
        current = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(first, "value", "doubled")
        in_flight = client.post(
            _view_support_url(first, "values"),
            headers={
                "Marimo-Session-Id": first["presentationSessionId"],
            },
            json={
                "revision": first["revision"],
                "projections": [projection],
                "activeProjections": [projection],
            },
        )
        removed = client.post(
            _view_support_url(current, "values"),
            headers={
                "Marimo-Session-Id": current["presentationSessionId"],
            },
            json={
                "revision": current["revision"],
                "projections": [projection],
                "activeProjections": [projection],
            },
        )
        unpublished = client.post(
            _view_support_url(current, "values"),
            headers={
                "Marimo-Session-Id": current["presentationSessionId"],
            },
            json={
                "revision": "unpublished",
                "projections": [projection],
                "activeProjections": [projection],
            },
        )

    assert first["revision"] != current["revision"]
    assert in_flight.status_code == 409
    assert in_flight.json()["error"] == "stale-projection-binding"
    assert removed.status_code == 400
    assert removed.json()["error"] == "projection-site-not-found"
    assert unpublished.status_code == 403
    assert unpublished.json()["error"] == "presentation-capability-forbidden"


def test_retained_value_revision_rejects_a_variable_moved_to_another_cell(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = published_dashboard(notebook_path)
    fake_session = _live_test_session(
        [
            SimpleNamespace(id="runtime-moved", code="doubled = 999", name="moved"),
            SimpleNamespace(id="runtime-other", code="x = 1", name="other"),
        ]
    )
    monkeypatch.setattr(
        kernel_projection_host,
        "current_session",
        lambda _context, _session_id: fake_session,
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        retained = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(retained, "value", "doubled")
        response = client.post(
            _view_support_url(retained, "values"),
            headers={
                "Marimo-Session-Id": retained["presentationSessionId"],
            },
            json={
                "revision": retained["revision"],
                "projections": [projection],
                "activeProjections": [projection],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "stale-projection-binding"
    assert response.json()["transient"] is False


def test_retained_value_revision_rejects_an_upstream_only_edit(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = published_dashboard(notebook_path)
    static = load_static_notebook(studio.notebook)
    rows = [
        SimpleNamespace(
            id=f"runtime-{index}",
            code=(cell.code.replace("x = 2", "x = 3") if index == 0 else cell.code),
            name=cell.name,
        )
        for index, cell in enumerate(static.cells)
    ]
    fake_session = _live_test_session(rows)
    monkeypatch.setattr(
        kernel_projection_host,
        "current_session",
        lambda _context, _session_id: fake_session,
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        retained = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(retained, "value", "doubled")
        response = client.post(
            _view_support_url(retained, "values"),
            headers={
                "Marimo-Session-Id": retained["presentationSessionId"],
            },
            json={
                "revision": retained["revision"],
                "projections": [projection],
                "activeProjections": [projection],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "stale-projection-binding"
    assert "dependency closure changed" in response.json()["message"]


def test_retained_value_revision_rejects_a_newly_resolved_reference(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8")
        .replace("x = 2", "y = 2")
        .replace("return (x,)", "return (y,)"),
        encoding="utf-8",
    )
    studio = published_dashboard(notebook_path)
    static = load_static_notebook(studio.notebook)
    rows = [
        SimpleNamespace(
            id=f"runtime-{index}",
            code=cell.code,
            name=cell.name,
        )
        for index, cell in enumerate(static.cells)
    ]
    rows.append(SimpleNamespace(id="runtime-x", code="x = 3", name="x_source"))
    fake_session = _live_test_session(rows)
    monkeypatch.setattr(
        kernel_projection_host,
        "current_session",
        lambda _context, _session_id: fake_session,
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        retained = client.get("/_marimo-studio/views/dashboard/config").json()
        projection = _projection_request(retained, "value", "doubled")
        response = client.post(
            _view_support_url(retained, "values"),
            headers={
                "Marimo-Session-Id": retained["presentationSessionId"],
            },
            json={
                "revision": retained["revision"],
                "projections": [projection],
                "activeProjections": [projection],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"] == "stale-projection-binding"
