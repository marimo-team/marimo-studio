from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import MutableMapping
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from marimo_studio import create_asgi_app
from marimo_studio._delivery.urls import (
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._server.presentation import service as presentation_service
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace.metadata import (
    read_notebook_metadata,
    update_notebook_config,
)
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import configured as _configured
from ..helpers import empty_notebook_source
from .app_test_support import (
    _artifact_base,
    _editor_mount_value,
    _presentation_fallback_url,
    _presentation_frame_sandbox,
    _runtime_mount_script,
)


def test_run_mode_serves_default_and_named_view_documents(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        default = client.get("/")
        named = client.get("/executive/")
        default_document = client.get(_presentation_fallback_url(default.text))
        named_document = client.get(_presentation_fallback_url(named.text))
        native_editor = client.get("/_marimo-studio/editor/")

    assert default.status_code == 200
    assert default.text.count('id="marimo-runtime-root"') == 1
    assert "/_marimo-studio/presentation/" in default.text
    assert (
        "/_marimo-studio/views/dashboard?marimo_studio_server=" in default_document.text
    )
    assert named.status_code == 200
    assert (
        "/_marimo-studio/views/executive?marimo_studio_server=" in named_document.text
    )
    assert native_editor.status_code == 404


def test_run_wasm_uses_the_trusted_wrapper_without_session_preservation(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        wrapper = client.get(
            "/dashboard/",
            params={"runtime": "wasm"},
            follow_redirects=False,
        )
        child = client.get(_presentation_fallback_url(wrapper.text))

    marker = "const config = Object.freeze("
    start = wrapper.text.index(marker) + len(marker)
    wrapper_config, _end = json.JSONDecoder().raw_decode(wrapper.text, start)

    assert wrapper.status_code == 200
    assert "location" not in wrapper.headers
    assert "marimo_studio_renewal" not in str(wrapper.url)
    assert "session_id" not in str(wrapper.url)
    assert wrapper.headers["content-security-policy"].startswith("default-src 'none'")
    assert wrapper_config["runtime"] == "wasm"
    assert wrapper_config["runtimeExplicit"] is True
    assert wrapper_config["replayEnabled"] is False
    assert 'data-marimo-studio-frame-blueprint=""' in wrapper.text
    assert "<marimo-cell" not in wrapper.text
    assert child.status_code == 200
    assert _editor_mount_value(child.text, "runtime") == "wasm"
    assert _editor_mount_value(child.text, "runtimeExplicit") is True
    assert _editor_mount_value(child.text, "renewalToken").startswith("d.")
    assert "runtimeSessionId" not in child.text
    assert child.headers["content-security-policy"].split()[0] == "sandbox"


def test_run_preserved_session_ignores_forged_studio_frame_identity(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def preserve(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True

    update_notebook_config(studio.notebook, preserve)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        response = client.get(
            "/dashboard/",
            params={
                STUDIO_CLIENT_QUERY_PARAM: "forged-client",
                DOCUMENT_LIFECYCLE_QUERY_PARAM: "7",
            },
        )
        raw_capability = client.get(_presentation_fallback_url(response.text))
        capability_artifact_base = _artifact_base(raw_capability.text)
        artifact_html = client.get(f"{capability_artifact_base}index.html")
        direct_artifact_base = (
            "/dashboard/_marimo-studio/artifacts/"
            + capability_artifact_base.split(
                "/dashboard/_marimo-studio/artifacts/",
                1,
            )[1]
        )
        direct_artifact_html = client.get(f"{direct_artifact_base}index.html")

    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert 'id="marimo-studio-presentation"' in response.text
    assert "allow-same-origin" not in _presentation_frame_sandbox(response.text)
    assert "<marimo-cell" not in response.text
    assert raw_capability.status_code == 200
    sandbox_policy = raw_capability.headers["content-security-policy"].split()
    assert sandbox_policy[0] == "sandbox"
    assert "allow-same-origin" not in sandbox_policy[1:]
    assert "<marimo-cell" in raw_capability.text
    assert artifact_html.status_code == 200
    assert artifact_html.headers["content-type"].startswith("text/html")
    artifact_sandbox_policy = artifact_html.headers["content-security-policy"].split()
    assert artifact_sandbox_policy[0] == "sandbox"
    assert "allow-same-origin" not in artifact_sandbox_policy[1:]
    direct_sandbox_policy = direct_artifact_html.headers[
        "content-security-policy"
    ].split()
    assert direct_artifact_html.status_code == 200
    assert direct_artifact_html.headers["access-control-allow-origin"] == "null"
    assert direct_sandbox_policy[0] == "sandbox"
    assert "allow-same-origin" not in direct_sandbox_policy[1:]


@pytest.mark.requires_node
def test_run_wrapper_freezes_the_validated_runtime_selection(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    def preserve(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, preserve)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        implicit = client.get("/dashboard/")
        implicit_runtime = client.get(_presentation_fallback_url(implicit.text))
        explicit = client.get("/dashboard/", params={"runtime": "wasm"})
        explicit_runtime = client.get(_presentation_fallback_url(explicit.text))
        unavailable = client.get("/dashboard/", params={"runtime": "forged"})

    marker = "const config = Object.freeze("

    def wrapper_config(document: str) -> dict[str, object]:
        start = document.index(marker) + len(marker)
        config, _end = json.JSONDecoder().raw_decode(document, start)
        assert isinstance(config, dict)
        return config

    assert wrapper_config(implicit.text)["runtime"] == "server"
    assert wrapper_config(implicit.text)["runtimeExplicit"] is False
    assert _editor_mount_value(implicit_runtime.text, "runtime") == "server"
    assert _editor_mount_value(implicit_runtime.text, "runtimeExplicit") is False
    assert _editor_mount_value(implicit_runtime.text, "runtimeSessionId")
    assert _editor_mount_value(implicit_runtime.text, "renewalToken").startswith("d.")
    assert wrapper_config(explicit.text)["runtime"] == "wasm"
    assert wrapper_config(explicit.text)["runtimeExplicit"] is True
    assert _editor_mount_value(explicit_runtime.text, "runtime") == "wasm"
    assert _editor_mount_value(explicit_runtime.text, "runtimeExplicit") is True
    assert _editor_mount_value(explicit_runtime.text, "renewalToken").startswith("d.")
    assert "runtimeSessionId" not in explicit_runtime.text
    expected_mount = {
        key: _editor_mount_value(explicit_runtime.text, key)
        for key in ("runtime", "runtimeExplicit", "supportUrl", "sessionId")
    }
    script = f"""
import assert from "node:assert/strict";
globalThis.window = globalThis;
globalThis.document = {{ documentElement: {{ dataset: {{}} }} }};
globalThis.setTimeout = () => 1;
(0, eval)({json.dumps(_runtime_mount_script(explicit_runtime.text))});
const descriptor = Object.getOwnPropertyDescriptor(
  globalThis,
  "__MARIMO_MOUNT_CONFIG__",
);
assert.equal(descriptor.writable, false);
assert.equal(descriptor.configurable, false);
for (const [key, value] of Object.entries({json.dumps(expected_mount)})) {{
  assert.deepEqual(descriptor.value[key], value);
}}
const retained = descriptor.value;
try {{ globalThis.__MARIMO_MOUNT_CONFIG__ = {{ runtime: "forged" }}; }} catch {{}}
assert.equal(globalThis.__MARIMO_MOUNT_CONFIG__, retained);
"""
    subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        check=True,
        capture_output=True,
        text=True,
    )
    assert unavailable.status_code == 400
    assert "unavailable" in unavailable.text


def test_run_mode_builds_and_serves_the_production_profile(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    provider = provider_registry().get(studio.view("dashboard").provider)
    build = provider.build

    def mark_profile(request):
        result = build(request)
        assert result.document is not None
        document = request.staging_root.joinpath(*result.document.parts)
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "</main>",
                f'<p data-build-profile="{request.profile}"></p></main>',
            ),
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(provider, "build", mark_profile)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        wrapper = client.get("/")
        response = client.get(_presentation_fallback_url(wrapper.text))

    assert response.status_code == 200
    assert 'data-build-profile="production"' in response.text


def test_mutable_studio_errors_are_not_cached(notebook_path: Path) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        config = client.get("/_marimo-studio/views/dashboard/config").json()
        missing_view = client.get("/_marimo-studio/views/missing/project")
        unsupported_source_method = client.post(
            f"{config['runtime']['data']['url']}"
            "_marimo-studio/views/dashboard/source/index.html",
        )

    assert missing_view.status_code == 404
    assert missing_view.headers["cache-control"] == "no-store"
    assert unsupported_source_method.status_code == 403
    assert unsupported_source_method.headers["cache-control"] == "no-store"


def test_view_entry_changes_refresh_the_presentation(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(presentation_service, "_SNAPSHOT_HISTORY_LIMIT", 2)
    studio = _configured(notebook_path)
    view = studio.views["dashboard"]
    entry = view.root / "index.html"

    with TestClient(create_asgi_app(studio.notebook)) as client:
        before_wrapper = client.get("/")
        before = client.get(_presentation_fallback_url(before_wrapper.text))
        before_entry = f"{_artifact_base(before.text)}index.html"
        source = client.get(before_entry)
        not_modified = client.get(
            before_entry,
            headers={"If-None-Match": source.headers["etag"]},
        )
        entry.write_text(
            entry.read_text(encoding="utf-8").replace(
                "</body>",
                "<!-- fresh --></body>",
            ),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 2
        while True:
            after_wrapper = client.get("/")
            after = client.get(_presentation_fallback_url(after_wrapper.text))
            after_entry = f"{_artifact_base(after.text)}index.html"
            if after_entry != before_entry or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        retained = client.get(before_entry)
        current_artifact_revision = re.search(
            r"/artifacts/([0-9a-f]{64})/",
            after_entry,
        )
        assert current_artifact_revision is not None
        mismatched_artifact = re.sub(
            r"/artifacts/[0-9a-f]{64}/",
            f"/artifacts/{current_artifact_revision.group(1)}/",
            before_entry,
        )
        escaped = client.get(mismatched_artifact)
        cross_view = client.get(
            before_entry.replace(
                "/dashboard/_marimo-studio/artifacts/",
                "/executive/_marimo-studio/artifacts/",
            )
        )
        cross_session = client.get(
            re.sub(
                r"(r\.[^.]+\.[^.]+\.)s_[a-z0-9]{6}\.",
                r"\1s_other1.",
                before_entry,
                count=1,
            )
        )
        refreshed = client.get(after_entry)
        entry.write_text(
            entry.read_text(encoding="utf-8").replace(
                "<!-- fresh -->",
                "<!-- newest -->",
            ),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 2
        while True:
            newest_wrapper = client.get("/")
            newest = client.get(_presentation_fallback_url(newest_wrapper.text))
            newest_entry = f"{_artifact_base(newest.text)}index.html"
            if newest_entry != after_entry or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        evicted = client.get(before_entry)

    assert source.status_code == 200
    assert source.headers["content-type"].startswith("text/html")
    assert source.headers["cache-control"] == ("private, max-age=31536000, immutable")
    assert source.headers["etag"].startswith('"sha256:')
    assert not_modified.status_code == 304
    assert retained.status_code == 200
    assert retained.text == source.text
    assert escaped.status_code == 403
    assert escaped.json()["error"] == "presentation-capability-forbidden"
    assert cross_view.status_code == 403
    assert cross_view.json()["error"] == "presentation-capability-forbidden"
    assert cross_session.status_code == 403
    assert cross_session.json()["error"] == "presentation-capability-forbidden"
    assert "<!-- fresh -->" in refreshed.text
    assert "<!-- newest -->" in newest.text
    assert evicted.status_code == 403
    assert evicted.json()["error"] == "presentation-capability-forbidden"
    assert before_entry != after_entry
    assert (
        before.headers["Marimo-Studio-Revision"]
        != after.headers["Marimo-Studio-Revision"]
    )


def test_revisiting_a_view_reuses_its_watcher_generation_snapshot(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = _configured(notebook_path)
    provider = provider_registry().get(studio.view("dashboard").provider)
    inspect = provider.inspect
    inspections: dict[str, int] = {}

    def count(request):
        project = request.project
        inspections[project.name] = inspections.get(project.name, 0) + 1
        return inspect(request)

    monkeypatch.setattr(provider, "inspect", count)
    with TestClient(create_asgi_app(studio.notebook)) as client:
        first = client.get("/_marimo-studio/views/dashboard/config")
        dashboard_inspections = inspections["dashboard"]
        executive = client.get("/_marimo-studio/views/executive/config")
        revisited = client.get("/_marimo-studio/views/dashboard/config")

    assert first.status_code == executive.status_code == revisited.status_code == 200
    assert inspections["dashboard"] == dashboard_inspections
    assert first.json()["revision"] == revisited.json()["revision"]


def test_empty_notebook_serves_a_ready_starter_view(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(empty_notebook_source(), encoding="utf-8")
    prepare_view(notebook)

    with TestClient(create_asgi_app(notebook)) as client:
        page = client.get("/")
        config = client.get("/_marimo-studio/views/dashboard/config")

    assert page.status_code == 200
    assert config.status_code == 200
    assert config.json()["projectionTargets"] == {"cells": {}, "variables": {}}
    assert config.json()["mounts"] == []
    assert config.json()["runtimeBindings"]["cellRefs"] == {}
    assert config.json()["diagnostics"] == []
    assert config.json()["showCellLogs"] is True


def test_runtime_injection_uses_structural_html_tags(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    (studio.views["dashboard"].root / "index.html").write_text(
        """\
<!doctype html>
<html>
  <head>
    <script>const headMarker = "</head>";</script>
  </head>
  <body>
    <main id="app-shell"></main>
    <script>const bodyMarker = "</body>";</script>
  </body>
</html>
""",
        encoding="utf-8",
    )

    with TestClient(create_asgi_app(studio.notebook)) as client:
        wrapper = client.get("/")
        response = client.get(_presentation_fallback_url(wrapper.text))

    assert response.status_code == 200
    assert '<script>const headMarker = "</head>";</script>' in response.text
    assert '<script>const bodyMarker = "</body>";</script>' in response.text
    assert (
        '<link data-marimo-studio-runtime rel="stylesheet" '
        'crossorigin="anonymous" href="'
    ) in response.text
    assert response.text.index("runtime.css") < response.text.index("const headMarker")
    assert response.text.index('id="marimo-runtime-root"') > response.text.index(
        "const bodyMarker"
    )


def test_run_mode_serves_the_configured_wasm_runtime_and_source(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)

    with TestClient(create_asgi_app(studio.notebook)) as client:
        unavailable = client.get("/_marimo-studio/views/dashboard/config?runtime=wasm")

    source = studio.notebook.read_text(encoding="utf-8")
    studio.notebook.write_text(
        source.replace(
            "# [tool.marimo-studio]",
            '# [tool.uv]\n# prerelease = "allow"\n#\n# [tool.marimo-studio]',
            1,
        ),
        encoding="utf-8",
    )

    def enable_wasm(config: MutableMapping[str, object]) -> None:
        config["runtime"] = "wasm"
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(studio.notebook, enable_wasm)
    configured = studio.notebook.read_bytes()
    with TestClient(create_asgi_app(studio.notebook)) as client:
        page = client.get("/")
        dashboard = client.get("/_marimo-studio/views/dashboard/config").json()
        executive = client.get("/_marimo-studio/views/executive/config").json()

    assert unavailable.status_code == 400
    assert unavailable.json()["error"] == "runtime-unavailable"
    assert '"runtime":"wasm"' in page.text
    assert dashboard["runtime"]["id"] == "wasm"
    assert dashboard["runtime"]["instance"] == executive["runtime"]["instance"]
    code = dashboard["runtime"]["data"]["code"]
    compile(code, "notebook.py", "exec")
    browser_source = notebook_path.with_name("browser.py")
    browser_source.write_bytes(code.encode("utf-8"))
    browser_metadata = read_notebook_metadata(browser_source)
    assert browser_metadata is not None
    assert set(browser_metadata) == {"requires-python", "dependencies"}
    assert list(browser_metadata["dependencies"]) == []
    assert studio.notebook.read_bytes() == configured


@pytest.mark.parametrize(
    "query",
    ["marimo_studio_unframed=1", "marimo_studio_unframed=1&marimo_studio_unframed=0"],
)
def test_unframed_view_preserves_document_sandbox(
    notebook_path: Path, query: str
) -> None:
    studio = _configured(notebook_path)
    with TestClient(create_asgi_app(studio.notebook)) as client:
        response = client.get(f"/dashboard/?{query}")
    assert response.status_code == 200
    assert "<marimo-cell" in response.text
    assert 'id="marimo-studio-presentation"' not in response.text
    policy = response.headers["content-security-policy"]
    assert policy.startswith("sandbox ")
    assert "allow-same-origin" not in policy
    assert _editor_mount_value(response.text, "runtime") == "server"
