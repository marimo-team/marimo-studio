import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { createServerTransportURL } from "../src/runtime/transport.ts";

const urls = () => [
  new URL("ws://example.test/base/ws?session_id=session&runtime=wasm&file=wrong.py"),
  new URL("https://example.test/base/sse?session_id=session&runtime=wasm&file=wrong.py"),
];

test("edit previews mark kernel transports as a kiosk consumer", () => {
  const configure = createServerTransportURL(true);

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("session_id"), "session");
    assert.deepEqual(url.searchParams.get("kiosk"), "true");
    assert.deepEqual(url.searchParams.has("runtime"), false);
    assert.deepEqual(url.searchParams.has("file"), false);
  }
});

test("run views remove Studio query state from Marimo transports", () => {
  const [ws, sse] = urls().map(createServerTransportURL(false));

  assert.deepEqual(ws?.toString(), "ws://example.test/base/ws?session_id=session");
  assert.deepEqual(sse?.toString(), "https://example.test/base/sse?session_id=session");
});

test("directory views select their notebook on kernel transports", () => {
  const configure = createServerTransportURL(false, "nested/notebook.py");

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("file"), "nested/notebook.py");
    assert.deepEqual(url.searchParams.has("runtime"), false);
  }
});
