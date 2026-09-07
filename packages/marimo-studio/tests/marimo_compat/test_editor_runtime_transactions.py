from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from marimo_studio._compat.server.editor_runtime import (
    _await_document_transactions_before_network_run,
    _serialize_document_transactions,
)

pytestmark = pytest.mark.requires_node


def _cells_module() -> bytes:
    source = (
        b"const FP=value=>value;"
        b"const Sg=operation=>{operation.cancel=()=>{};return operation};"
        b"const Sr=()=>globalThis.__documentClient;"
        b"const CT=0,zr=0,__tla=Promise.resolve();"
        b"var marimoStudioFlushDocumentChanges;"
        b"var _m=[],$P=Sg(()=>{let e=FP(_m);_m=[],e.length!==0&&"
        b"Sr().sendDocumentTransaction({changes:e})},400);"
        b"const queueChange=change=>_m.push(change);"
        b"export {queueChange,zr,__tla,CT as zt};"
    )
    return _serialize_document_transactions(source)


def _run_node(script: str) -> None:
    subprocess.run(
        ["node", "--input-type=module"],
        input=script,
        check=True,
        capture_output=True,
        text=True,
    )


def test_emitted_queue_keeps_retry_identity_and_new_edits_separate(
    tmp_path: Path,
) -> None:
    cells = tmp_path / "cells-test.js"
    cells.write_bytes(_cells_module())
    _run_node(
        f"""
import assert from "node:assert/strict";
import {{ pathToFileURL }} from "node:url";
import {{ MessageChannel }} from "node:worker_threads";
globalThis.MessageChannel = MessageChannel;
globalThis.frameElement = {{ hasAttribute: () => true }};
globalThis.location = {{ origin: "https://studio.test" }};
globalThis.addEventListener = () => {{}};
globalThis.removeEventListener = () => {{}};
Object.defineProperty(globalThis, "crypto", {{
  configurable: true,
  value: {{ getRandomValues: (values) => values.fill(0) }},
}});
const messages = [];
globalThis.parent = {{
  postMessage(message, _origin, ports = []) {{
    messages.push(message);
    if (message.type === "marimo-studio:editor-document-mutation") {{
      ports[0].postMessage({{
        schema: 1,
        type: "marimo-studio:editor-document-mutation-ready",
        generation: message.generation,
      }});
      ports[0].close();
    }}
  }},
}};
const calls = [];
let module;
globalThis.__documentClient = {{
  async sendDocumentTransaction(request) {{
    calls.push(structuredClone(request));
    if (calls.length === 1) {{
      module.queueChange({{ id: "new" }});
      throw new Error("response lost");
    }}
    return calls.length === 2;
  }},
}};
module = await import(pathToFileURL({str(cells)!r}).href);
module.queueChange({{ id: "retry" }});
await assert.rejects(module.studioFlushDocumentChanges(), /response lost/);
await module.studioFlushDocumentChanges();
assert.deepEqual(calls.map((call) => call.changes), [
  [{{ id: "retry" }}],
  [{{ id: "retry" }}],
  [{{ id: "new" }}],
]);
assert.equal(calls[0].studioOperationId, calls[1].studioOperationId);
assert.notEqual(calls[1].studioOperationId, calls[2].studioOperationId);
assert.match(calls[0].studioOperationId, /^[A-Za-z0-9_-]{{16,128}}$/);
assert.equal(calls[0].studioOperationId.length, calls[2].studioOperationId.length);
assert.deepEqual(
  messages
    .filter(
      (message) => message.type === "marimo-studio:editor-document-transaction-applied",
    )
    .map((message) => message.changed),
  [true, false],
);
"""
    )


def test_rewritten_network_module_requires_exact_changed_header(
    tmp_path: Path,
) -> None:
    cells = tmp_path / "cells-test.js"
    cells.write_bytes(_cells_module())
    source = (
        b'import {zr as zj,__tla as Mj}from"./cells-test.js";'
        b"const st=async()=>{};const ve=async value=>value;"
        b"function createNetwork(post){let t=()=>({POST:post}),e=()=>({}),"
        b"r=()=>({header:e()});return{sendComponentValues:()=>{},"
        b'sendSave:n=>t().POST("/api/kernel/save",{body:n,parseAs:"text",params:r()}).then(ve),'
        b"sendDocumentTransaction:async n=>(await st(),t().POST("
        b'"/api/document/transaction",'
        b"{body:n,params:r()}).then(ve)),"
        b'sendRun:async n=>(await st(),t().POST("/api/kernel/run",{body:n,params:r()})'
        b".then(ve))}};export {createNetwork};"
    )

    index = tmp_path / "index-test.js"
    index.write_bytes(_await_document_transactions_before_network_run(source))
    _run_node(
        f"""
import assert from "node:assert/strict";
import {{ pathToFileURL }} from "node:url";
globalThis.frameElement = null;
globalThis.location = {{ origin: "https://studio.test" }};
let changed = "true";
const calls = [];
globalThis.__documentClient = {{ sendDocumentTransaction: async () => false }};
globalThis.__post = async (url, options) => {{
  calls.push([url, structuredClone(options)]);
  const headers = new Headers();
  if (changed !== null) headers.set("marimo-studio-document-changed", changed);
  return {{ response: {{ headers }} }};
}};
const {{ createNetwork }} = await import(pathToFileURL({str(index)!r}).href);
const network = createNetwork(globalThis.__post);
const operation = "operation-0000001";
assert.equal(
  await network.sendDocumentTransaction({{
    changes: [{{ id: 1 }}],
    studioOperationId: operation,
  }}),
  true,
);
changed = "false";
assert.equal(
  await network.sendDocumentTransaction({{
    changes: [{{ id: 2 }}],
    studioOperationId: operation,
  }}),
  false,
);
changed = null;
await assert.rejects(
  network.sendDocumentTransaction({{ changes: [], studioOperationId: operation }}),
  /evidence is unavailable/,
);
assert.deepEqual(calls[0], [
  "/api/document/transaction",
  {{
    body: {{ changes: [{{ id: 1 }}] }},
    headers: {{ "Marimo-Studio-Document-Operation": operation }},
    params: {{ header: {{}} }},
  }},
]);
const peerCalls = [];
const peer = createNetwork(async (url, options) => {{
  peerCalls.push([url, options]);
  const headers = new Headers({{ "marimo-studio-document-changed": "false" }});
  return {{ response: {{ headers }} }};
}});
assert.equal(await peer.sendDocumentTransaction({{
  changes: [],
  studioOperationId: "peer-00000000001",
}}), false);
assert.equal(peerCalls.length, 1);
assert.equal(calls.length, 3);
"""
    )


def test_emitted_queue_closes_both_ports_when_barrier_transfer_fails(
    tmp_path: Path,
) -> None:
    cells = tmp_path / "cells-transfer.js"
    cells.write_bytes(_cells_module())
    _run_node(
        f"""
import assert from "node:assert/strict";
import {{ pathToFileURL }} from "node:url";
const ports = [];
globalThis.MessageChannel = class {{
  constructor() {{
    const port = () => ({{
      closed: false,
      close() {{ this.closed = true; }},
      start() {{}},
    }});
    this.port1 = port();
    this.port2 = port();
    ports.push(this.port1, this.port2);
  }}
}};
globalThis.frameElement = {{ hasAttribute: () => true }};
globalThis.location = {{ origin: "https://studio.test" }};
globalThis.addEventListener = () => {{}};
globalThis.removeEventListener = () => {{}};
globalThis.parent = {{
  postMessage() {{ throw new DOMException("Port transfer failed", "DataCloneError"); }},
}};
let requests = 0;
globalThis.__documentClient = {{
  async sendDocumentTransaction() {{ requests += 1; return true; }},
}};
const module = await import(pathToFileURL({str(cells)!r}).href);
module.queueChange({{ id: "pending" }});
await assert.rejects(module.studioFlushDocumentChanges(), /Port transfer failed/);
assert.deepEqual(ports.map((port) => port.closed), [true, true]);
assert.equal(requests, 0);
"""
    )
