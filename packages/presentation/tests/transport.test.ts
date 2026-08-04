import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { configureServerTransport, type RuntimeTransport } from "../src/runtime/transport.ts";

const runtime = (): RuntimeTransport<string> => ({
  getWsURL: (sessionId) =>
    new URL(`ws://example.test/base/ws?session_id=${sessionId}&runtime=wasm`),
  getSseURL: (sessionId) =>
    new URL(`https://example.test/base/sse?session_id=${sessionId}&runtime=wasm`),
});

test("edit previews mark kernel transports as a kiosk consumer", () => {
  const manager = runtime();

  configureServerTransport(manager, true);

  for (const url of [manager.getWsURL("session"), manager.getSseURL("session")]) {
    assert.deepEqual(url.searchParams.get("session_id"), "session");
    assert.deepEqual(url.searchParams.get("kiosk"), "true");
    assert.deepEqual(url.searchParams.has("runtime"), false);
  }
});

test("run views remove Studio query state from Marimo transports", () => {
  const manager = runtime();

  configureServerTransport(manager, false);

  assert.deepEqual(
    manager.getWsURL("session").toString(),
    "ws://example.test/base/ws?session_id=session",
  );
  assert.deepEqual(
    manager.getSseURL("session").toString(),
    "https://example.test/base/sse?session_id=session",
  );
});
