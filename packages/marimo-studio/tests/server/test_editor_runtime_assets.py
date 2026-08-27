from __future__ import annotations

import asyncio
import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import marimo
import pytest
from starlette.responses import FileResponse
from starlette.testclient import TestClient
from starlette.types import Message

from marimo_studio._compat.server.editor_runtime import (
    _BOUNDED_LSP_RECONNECT,
    _ORDERED_NETWORK_SEND_RUN,
    _ORDERED_NETWORK_SEND_SAVE,
    _QUERY_PARAM_HANDLERS,
    PrivateEditorRuntimeBootstrap,
    _await_document_transactions_before_network_run,
    _backoff_lsp_reconnects,
    _protect_editor_query_parameters,
    _serialize_document_transactions,
)
from marimo_studio._views.api import ensure_view
from marimo_studio.errors import ProtocolError

from ..app_helpers import configured as _configured
from ..app_helpers import edit_mode as _edit_mode
from ..app_helpers import marimo_app as _marimo_app
from ..helpers import notebook_source
from .app_test_support import (
    _editor_mount_value,
    _studio_bootstrap,
    _studio_host,
)


class _ResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []
        self.images: list[dict[str, str | None]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "link":
            self.links.append(dict(attrs))
        elif tag == "img":
            self.images.append(dict(attrs))


def _resources(source: str) -> _ResourceParser:
    parser = _ResourceParser()
    parser.feed(source)
    return parser


def test_configured_editor_starts_its_runtime_without_user_action(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, programmatic=True)
    _edit_mode(app)
    with TestClient(app) as client:
        workspace = client.get("/studio/")
        response = client.get(_studio_bootstrap(workspace.text)["urls"]["editor"])

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert _editor_mount_value(response.text, "runtimeConfig") == [
        {
            "url": "http://testserver/_marimo-studio/editor/",
            "lazy": False,
        }
    ]
    assert (
        _editor_mount_value(response.text, "configOverrides")["runtime"][
            "auto_instantiate"
        ]
        is True
    )


def test_unconfigured_editor_keeps_its_runtime_lazy(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "plain.py"
    notebook.write_text(
        notebook_source(tmp_path / "executed"),
        encoding="utf-8",
    )
    app = _marimo_app(notebook, programmatic=True)
    _edit_mode(app)

    with TestClient(app) as client:
        host = client.get("/")
        response = client.get(_studio_host(host.text)["urls"]["editor"])

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert _editor_mount_value(response.text, "runtimeConfig") is None
    runtime_overrides = _editor_mount_value(response.text, "configOverrides")["runtime"]
    assert "auto_instantiate" not in runtime_overrides


def test_editor_rewrite_removes_only_welcome_texture_preloads() -> None:
    source = b"""<html>
<head>
    <link rel="preload" href="./assets/gradient-test_hash.png" as="image" />
    <link rel="preload" href="./assets/noise-test_hash.png" as="image" />
    <link rel="preload" href="./assets/font-test.woff2" as="font" />
    <link rel="modulepreload" href="./assets/app-test.js" />
    <link rel="stylesheet" href="./assets/gradient-test_hash.png" />
</head>
<body>
    <img src="./assets/noise-test_hash.png" />
    <script>value: Object.freeze({"runtimeConfig":[],"configOverrides":{}})</script>
</body>
</html>
"""

    rewritten = (
        PrivateEditorRuntimeBootstrap()
        .rewrite(
            source,
            runtime_url="http://testserver/_marimo-studio/editor/",
        )
        .decode()
    )

    resources = _resources(rewritten)
    assert resources.links == [
        {
            "rel": "preload",
            "href": "./assets/font-test.woff2",
            "as": "font",
        },
        {"rel": "modulepreload", "href": "./assets/app-test.js"},
        {"rel": "stylesheet", "href": "./assets/gradient-test_hash.png"},
    ]
    assert resources.images == [{"src": "./assets/noise-test_hash.png"}]


def test_editor_rewrite_rejects_welcome_preload_shape_drift() -> None:
    source = b"""<html>
<head>
    <link rel="preload" href="./assets/gradient-test_hash.png" as="image" />
</head>
<body>
    <script>value: Object.freeze({"runtimeConfig":[],"configOverrides":{}})</script>
</body>
</html>
"""

    with pytest.raises(ProtocolError, match="welcome texture preloads changed"):
        PrivateEditorRuntimeBootstrap().rewrite(
            source,
            runtime_url="http://testserver/_marimo-studio/editor/",
        )


def test_configured_editor_rewrites_the_pinned_runtime_assets(
    notebook_path: Path,
) -> None:
    studio = _configured(notebook_path)
    app = _marimo_app(studio.notebook, programmatic=True)
    _edit_mode(app)
    assets = Path(marimo.__file__).parent / "_static" / "assets"
    cell_editor = next(assets.glob("cell-editor-*.js"))
    runtime_config = next(
        path for path in assets.glob("config-*.js") if b"getLSPURL" in path.read_bytes()
    )
    cells = next(
        path
        for path in assets.glob("cells-*.js")
        if b"sendDocumentTransaction({changes:e})" in path.read_bytes()
    )
    index = next(
        path
        for path in assets.glob("index-*.js")
        if b'sendRun:async n=>(await st(),t().POST("/api/kernel/run"'
        in path.read_bytes()
    )
    panels = next(
        path
        for path in assets.glob("panels-*.js")
        if b"const aA={append:" in path.read_bytes()
    )

    with TestClient(app) as client:
        responses = {
            path.name: client.get(
                f"/_marimo-studio/editor/assets/{path.name}",
                params={"file": str(studio.notebook)},
                headers={
                    "If-None-Match": "cached-native-asset",
                    "If-Range": "cached-native-asset",
                    "Range": "bytes=0-127",
                },
            )
            for path in (cell_editor, runtime_config, cells, index, panels)
        }

    for response in responses.values():
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "accept-ranges" not in response.headers
        assert "content-range" not in response.headers
        assert "etag" not in response.headers
        assert "last-modified" not in response.headers
    cell_editor_content = responses[cell_editor.name].content
    runtime_config_content = responses[runtime_config.name].content
    cells_content = responses[cells.name].content
    index_content = responses[index.name].content
    panels_content = responses[panels.name].content
    assert cell_editor_content.count(b't.copilot==="github"?Ru.of(Rm()):[]') == 1
    assert (
        runtime_config_content.count(
            b"new URL(this.formatWsURL(`/lsp/${t}`).toString().replace("
            b'"/_marimo-studio/editor/lsp/","/lsp/"))'
        )
        == 1
    )
    for marker in (
        b"marimoStudioRetryDocumentChanges",
        b"this.options.onConnectionFailure",
    ):
        assert marker in cells_content
    for marker in (
        b"studioAwaitDocumentMutation",
        b"studioFlushDocumentChanges",
        b"studioReportDocumentSave",
    ):
        assert marker in index_content
    for marker in (
        b"marimoStudioImmutableQueryKeys",
        b"marimoStudioRetainedQueryKeys",
    ):
        assert marker in panels_content


@pytest.mark.parametrize(
    ("rewrite", "message"),
    (
        pytest.param(
            _backoff_lsp_reconnects,
            "editor LSP reconnect scheduler",
            id="lsp-reconnect",
        ),
        pytest.param(
            _serialize_document_transactions,
            "document transaction queue",
            id="document-queue",
        ),
        pytest.param(
            _await_document_transactions_before_network_run,
            "editor network cell imports",
            id="network-runner",
        ),
        pytest.param(
            _protect_editor_query_parameters,
            "editor query parameter handlers",
            id="query-handlers",
        ),
    ),
)
def test_editor_runtime_asset_rewrites_fail_closed(
    rewrite: Any,
    message: str,
) -> None:
    with pytest.raises(ProtocolError, match=message):
        rewrite(b"export const changed = true;")


@pytest.mark.requires_node
def test_native_save_and_run_wait_for_document_flush() -> None:
    save = _ORDERED_NETWORK_SEND_SAVE.decode()
    run = _ORDERED_NETWORK_SEND_RUN.decode()
    script = f"""
import assert from "node:assert/strict";
let generation = 0;
let flushFailure = false;
let resolveBarrier;
const barrier = new Promise((resolve) => {{ resolveBarrier = resolve; }});
const reports = [];
const requests = [];
const pending = new Map();
const studioFlushDocumentChanges = async () => {{
  generation = Math.max(generation, 1);
  if (flushFailure) throw new Error("preview gate failed");
}};
const studioAwaitDocumentMutation = () => barrier;
const studioDocumentMutationGeneration = () => generation;
const studioReportDocumentSave = (captured, succeeded) =>
  reports.push([captured, succeeded]);
const st = async () => {{}};
const r = () => ({{}});
const ve = (value) => value;
const t = () => ({{
  POST(url, options) {{
    requests.push([url, options.body, generation]);
    return new Promise((resolve, reject) =>
      pending.set(options.body, {{ resolve, reject }}));
  }},
}});
const client = {{ {save}, {run} }};

const running = client.sendRun("run");
await Promise.resolve();
assert.equal(requests.length, 0);
resolveBarrier();
await Promise.resolve();
await Promise.resolve();
assert.equal(requests[0][0], "/api/kernel/run");
pending.get("run").resolve("ran");
await running;

const first = client.sendSave("first");
while (!pending.has("first")) await Promise.resolve();
generation = 2;
const second = client.sendSave("second");
while (!pending.has("second")) await Promise.resolve();
pending.get("second").resolve("saved second");
await second;
pending.get("first").reject(new Error("older save failed"));
await assert.rejects(first, /older save failed/);
assert.deepEqual(reports, [[2, true], [1, false]]);
assert.equal(requests.find((entry) => entry[1] === "first")[2], 1);
assert.equal(requests.find((entry) => entry[1] === "second")[2], 2);
flushFailure = true;
await assert.rejects(client.sendRun("blocked"), /preview gate failed/);
assert.equal(requests.some((entry) => entry[1] === "blocked"), false);
await assert.rejects(client.sendSave("recovery"), /preview gate failed/);
assert.equal(requests.some((entry) => entry[1] === "recovery"), false);
"""
    subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.requires_node
def test_lsp_reconnect_scheduler_honors_transport_lifecycle() -> None:
    expression = _BOUNDED_LSP_RECONNECT.decode()
    script = f"""
import assert from "node:assert/strict";
const schedule = new Function("t", `return (${{{json.dumps(expression)}}});`);
const wait = () => new Promise((resolve) => setTimeout(resolve, 5));

const live = {{
  isClosed: false,
  reconnects: 0,
  options: {{ retryDelayMs: 0 }},
  reconnect() {{ this.reconnects += 1; }},
}};
schedule.call(live, new Error("closed"));
await wait();
assert.equal(live.reconnects, 1);

const closed = {{ ...live, isClosed: true, reconnects: 0 }};
schedule.call(closed, new Error("closed"));
await wait();
assert.equal(closed.reconnects, 0);

const terminal = {{
  ...live,
  failures: 0,
  reconnects: 0,
  options: {{
    retryDelayMs: 0,
    onConnectionFailure() {{ terminal.failures += 1; }},
  }},
}};
schedule.call(terminal, new Error("closed"));
await wait();
assert.equal(terminal.failures, 1);
assert.equal(terminal.reconnects, 0);
"""
    subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.requires_node
def test_editor_query_handlers_preserve_private_authority() -> None:
    handlers = _protect_editor_query_parameters(_QUERY_PARAM_HANDLERS).decode()
    initial = (
        "https://studio.test/editor/?file=first.py&public=one&"
        "marimo_studio_client=client-1&file=second.py&public=two&"
        "session_id=s_123456&marimo_studio_editor=capability&"
        "marimo_studio_query_operation=query-old#section"
    )
    script = (
        """
const historyEntries = [];
globalThis.window = {
  location: { href: "https://studio.test/editor/" },
  history: {
    pushState(_state, _title, target) {
      const next = new URL(String(target), window.location.href);
      window.location.href = next.href;
      historyEntries.push(next.href);
    },
  },
};
"""
        + handlers
        + """
const initial = """
        + json.dumps(initial)
        + """;
const apply = (operation, data) => {
  window.location.href = initial;
  historyEntries.length = 0;
  aA[operation](data);
  return { href: window.location.href, writes: historyEntries.length };
};
const results = {
  clear: apply("clear"),
  append: apply("append", { key: "public", value: "three" }),
  set: apply("set", { key: "public", value: "updated" }),
  setMany: apply("set", { key: "public", value: ["alpha", "beta"] }),
  deleteOne: apply("delete", { key: "public", value: "one" }),
  deleteAll: apply("delete", { key: "public", value: null }),
  setPrivate: apply("set", { key: "file", value: "forged.py" }),
  appendPrivate: apply("append", { key: "session_id", value: "forged" }),
  deletePrivate: apply("delete", {
    key: "marimo_studio_editor",
    value: null,
  }),
  setOperation: apply("set", {
    key: "marimo_studio_query_operation",
    value: "query-new",
  }),
  deleteOperation: apply("delete", {
    key: "marimo_studio_query_operation",
    value: null,
  }),
};
console.log(JSON.stringify(results));
"""
    )
    completed = subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        check=True,
        capture_output=True,
        text=True,
    )
    results = json.loads(completed.stdout)

    private = [
        ("file", "first.py"),
        ("marimo_studio_client", "client-1"),
        ("file", "second.py"),
        ("session_id", "s_123456"),
        ("marimo_studio_editor", "capability"),
        ("marimo_studio_query_operation", "query-old"),
    ]
    initial_query = [
        ("file", "first.py"),
        ("public", "one"),
        ("marimo_studio_client", "client-1"),
        ("file", "second.py"),
        ("public", "two"),
        ("session_id", "s_123456"),
        ("marimo_studio_editor", "capability"),
        ("marimo_studio_query_operation", "query-old"),
    ]

    def query(name: str) -> list[tuple[str, str]]:
        parts = urlsplit(results[name]["href"])
        assert parts.path == "/editor/"
        assert parts.fragment == "section"
        return parse_qsl(parts.query, keep_blank_values=True)

    assert query("clear") == private
    assert query("append") == [*initial_query, ("public", "three")]
    assert query("set") == [
        ("file", "first.py"),
        ("public", "updated"),
        ("marimo_studio_client", "client-1"),
        ("file", "second.py"),
        ("session_id", "s_123456"),
        ("marimo_studio_editor", "capability"),
        ("marimo_studio_query_operation", "query-old"),
    ]
    assert query("setMany") == [
        *private,
        ("public", "alpha"),
        ("public", "beta"),
    ]
    assert query("deleteOne") == [
        ("file", "first.py"),
        ("marimo_studio_client", "client-1"),
        ("file", "second.py"),
        ("public", "two"),
        ("session_id", "s_123456"),
        ("marimo_studio_editor", "capability"),
        ("marimo_studio_query_operation", "query-old"),
    ]
    assert query("deleteAll") == private
    for name in ("setPrivate", "appendPrivate", "deletePrivate"):
        assert results[name] == {"href": initial, "writes": 0}
    assert query("setOperation") == [
        *initial_query[:-1],
        ("marimo_studio_query_operation", "query-new"),
    ]
    assert query("deleteOperation") == initial_query[:-1]
    for name in (
        "clear",
        "append",
        "set",
        "setMany",
        "deleteOne",
        "deleteAll",
        "setOperation",
        "deleteOperation",
    ):
        assert results[name]["writes"] == 1


def test_cell_editor_rewrite_disables_path_send_and_partial_responses(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "cell-editor-test.js"
    asset.write_bytes(b"const extensions = [Ru.of(Rm())];")
    observed_scope: dict[str, object] = {}
    messages: list[Message] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        observed_scope.update(scope)
        await FileResponse(asset, media_type="text/javascript")(scope, receive, send)

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    scope = cast(
        Any,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/assets/cell-editor-test.js",
            "raw_path": b"/assets/cell-editor-test.js",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"if-range", b"native-etag"),
                (b"range", b"bytes=0-4"),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "extensions": {"http.response.pathsend": {}},
        },
    )

    served = asyncio.run(
        PrivateEditorRuntimeBootstrap().serve(
            app,
            scope,
            receive,
            send,
            resource_path="/assets/cell-editor-test.js",
            runtime_url="http://testserver/_marimo-studio/editor/",
            eager_runtime=False,
        )
    )

    assert served is True
    assert observed_scope["headers"] == [(b"accept-encoding", b"identity")]
    assert observed_scope["extensions"] == {}
    assert all(message["type"] != "http.response.pathsend" for message in messages)
    body = b"".join(
        cast(bytes, message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    )
    assert body == b'const extensions = [t.copilot==="github"?Ru.of(Rm()):[]];'


def test_editor_root_rewrite_requires_a_complete_identity_response() -> None:
    source = b"""<html>
<head>
    <link rel="preload" href="./assets/gradient-test_hash.png" as="image" />
    <link rel="preload" href="./assets/noise-test_hash.png" as="image" />
    <link rel="preload" href="./assets/font-test.woff2" as="font" />
    <link rel="modulepreload" href="./assets/app-test.js" />
</head>
<body>
    <script>value: Object.freeze({
        "runtimeConfig": null,
        "configOverrides": {"runtime": {"show_tracebacks": false}}
    })</script>
</body>
</html>
"""
    observed_scope: dict[str, object] = {}
    messages: list[Message] = []

    async def app(scope: Any, _receive: Any, send: Any) -> None:
        observed_scope.update(scope)
        headers = dict(scope.get("headers", ()))
        if b"if-none-match" in headers:
            await send({"type": "http.response.start", "status": 304, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        if b"range" in headers:
            await send(
                {
                    "type": "http.response.start",
                    "status": 206,
                    "headers": [(b"content-type", b"text/html")],
                }
            )
            await send({"type": "http.response.body", "body": source[:32]})
            return
        if headers.get(b"accept-encoding") != b"identity":
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/html"),
                        (b"content-encoding", b"gzip"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b"encoded"})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            }
        )
        await send({"type": "http.response.body", "body": source})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    scope = cast(
        Any,
        {
            "type": "http",
            "method": "GET",
            "headers": [
                (b"accept-encoding", b"gzip"),
                (b"if-none-match", b"native-etag"),
                (b"if-range", b"native-etag"),
                (b"range", b"bytes=0-31"),
            ],
            "extensions": {"http.response.pathsend": {}},
        },
    )

    served = asyncio.run(
        PrivateEditorRuntimeBootstrap().serve(
            app,
            scope,
            receive,
            send,
            resource_path="/",
            runtime_url="http://testserver/_marimo-studio/editor/",
            eager_runtime=False,
        )
    )

    assert served is True
    assert observed_scope["headers"] == [(b"accept-encoding", b"identity")]
    assert observed_scope["extensions"] == {}
    start = messages[0]
    assert start["status"] == 200
    headers = dict(cast(list[tuple[bytes, bytes]], start["headers"]))
    assert headers[b"cache-control"] == b"no-store"
    body = b"".join(
        cast(bytes, message.get("body", b""))
        for message in messages
        if message["type"] == "http.response.body"
    ).decode()
    resources = _resources(body)
    assert resources.links == [
        {
            "rel": "preload",
            "href": "./assets/font-test.woff2",
            "as": "font",
        },
        {"rel": "modulepreload", "href": "./assets/app-test.js"},
    ]
    assert "modulepreload" in body
    assert _editor_mount_value(body, "runtimeConfig") is None
    assert (
        "auto_instantiate"
        not in _editor_mount_value(body, "configOverrides")["runtime"]
    )


def test_editor_bootstrap_delegates_head_requests() -> None:
    called = False

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        nonlocal called
        called = True

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Message) -> None:
        return None

    served = asyncio.run(
        PrivateEditorRuntimeBootstrap().serve(
            app,
            cast(Any, {"type": "http", "method": "HEAD"}),
            receive,
            send,
            resource_path="/",
            runtime_url="http://testserver/_marimo-studio/editor/",
            eager_runtime=False,
        )
    )

    assert served is False
    assert called is False


def test_unconfigured_editor_cannot_cache_unadapted_runtime_assets(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "plain.py"
    notebook.write_text(
        notebook_source(tmp_path / "executed"),
        encoding="utf-8",
    )
    app = _marimo_app(notebook, programmatic=True)
    _edit_mode(app)
    assets = Path(marimo.__file__).parent / "_static" / "assets"
    cell_editor = next(assets.glob("cell-editor-*.js"))
    runtime_config = next(
        path for path in assets.glob("config-*.js") if b"getLSPURL" in path.read_bytes()
    )
    cells = next(
        path
        for path in assets.glob("cells-*.js")
        if b"sendDocumentTransaction({changes:e})" in path.read_bytes()
    )
    index = next(
        path
        for path in assets.glob("index-*.js")
        if b'sendRun:async n=>(await st(),t().POST("/api/kernel/run"'
        in path.read_bytes()
    )
    panels = next(
        path
        for path in assets.glob("panels-*.js")
        if b"const aA={append:" in path.read_bytes()
    )
    urls = [
        f"/_marimo-studio/editor/assets/{path.name}"
        for path in (cell_editor, runtime_config, cells, index, panels)
    ]

    with TestClient(app) as client:
        before = [client.get(url, params={"file": str(notebook)}) for url in urls]
        ensure_view(notebook)
        after = [
            client.get(
                url,
                params={"file": str(notebook)},
                headers={"If-None-Match": "cached-native-asset"},
            )
            for url in urls
        ]

    for response in (*before, *after):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "etag" not in response.headers
    assert before[0].content.count(b't.copilot==="github"?Ru.of(Rm()):[]') == 1
    assert before[1].content.count(b'"/_marimo-studio/editor/lsp/","/lsp/"') == 1
    for marker in (
        b"studioAwaitDocumentMutation",
        b"studioFlushDocumentChanges",
        b"studioReportDocumentSave",
    ):
        assert marker in before[2].content
        assert marker in before[3].content
    for marker in (
        b"marimoStudioRetainedQueryKeys",
        b"marimoStudioImmutableQueryKeys",
    ):
        assert marker in before[4].content
    assert [response.content for response in before] == [
        response.content for response in after
    ]
