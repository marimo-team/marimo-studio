import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { configureKioskTransport, type RuntimeTransport } from "../src/runtime/transport.ts";

const runtime = (): RuntimeTransport<string> => ({
  getWsURL: (sessionId) => new URL(`ws://example.test/base/ws?session_id=${sessionId}`),
  getSseURL: (sessionId) => new URL(`https://example.test/base/sse?session_id=${sessionId}`),
});

test("edit previews mark kernel transports as a kiosk consumer", () => {
  const manager = runtime();

  configureKioskTransport(manager, true);

  for (const url of [manager.getWsURL("session"), manager.getSseURL("session")]) {
    assert.deepEqual(url.searchParams.get("session_id"), "session");
    assert.deepEqual(url.searchParams.get("kiosk"), "true");
  }
});

test("run views keep Marimo transport URLs unchanged", () => {
  const manager = runtime();

  configureKioskTransport(manager, false);

  assert.deepEqual(
    manager.getWsURL("session").toString(),
    "ws://example.test/base/ws?session_id=session",
  );
  assert.deepEqual(
    manager.getSseURL("session").toString(),
    "https://example.test/base/sse?session_id=session",
  );
});
