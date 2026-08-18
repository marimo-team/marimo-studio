import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { createServerTransportURL } from "../src/runtime/transport.ts";

const urls = () => [
  new URL("ws://example.test/base/ws?session_id=session&runtime=wasm&file=wrong.py"),
  new URL("https://example.test/base/sse?session_id=session&runtime=wasm&file=wrong.py"),
];

test("edit previews mark kernel transports as a kiosk consumer", () => {
  const configure = createServerTransportURL(true, undefined, "server-instance");

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("session_id"), "session");
    assert.deepEqual(url.searchParams.get("kiosk"), "true");
    assert.deepEqual(url.searchParams.get("marimo_studio_server"), "server-instance");
    assert.deepEqual(url.searchParams.has("runtime"), false);
    assert.deepEqual(url.searchParams.has("file"), false);
  }
});

test("run views remove Studio query state from Marimo transports", () => {
  const [ws, sse] = urls().map(createServerTransportURL(false, undefined, "server-instance"));

  assert.deepEqual(
    ws?.toString(),
    "ws://example.test/base/ws?session_id=session&marimo_studio_server=server-instance",
  );
  assert.deepEqual(
    sse?.toString(),
    "https://example.test/base/sse?session_id=session&marimo_studio_server=server-instance",
  );
});

test("directory views select their notebook on kernel transports", () => {
  const configure = createServerTransportURL(false, "nested/notebook.py", "server-instance");

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("file"), "nested/notebook.py");
    assert.deepEqual(url.searchParams.has("runtime"), false);
  }
});
