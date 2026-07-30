import { assertEquals, assertStrictEquals } from "@std/assert";

import {
  configureKioskTransport,
  type RuntimeTransport,
} from "../src/marimo-adapter/transport.ts";

const runtime = (): RuntimeTransport<string> => ({
  getWsURL: (sessionId) =>
    new URL(`ws://example.test/base/ws?session_id=${sessionId}`),
  getSseURL: (sessionId) =>
    new URL(`https://example.test/base/sse?session_id=${sessionId}`),
});

Deno.test("edit previews mark kernel transports as a kiosk consumer", () => {
  const manager = runtime();

  configureKioskTransport(manager, true);

  for (
    const url of [
      manager.getWsURL("session"),
      manager.getSseURL("session"),
    ]
  ) {
    assertEquals(url.searchParams.get("session_id"), "session");
    assertEquals(url.searchParams.get("kiosk"), "true");
  }

  const configured = manager.getWsURL;
  configureKioskTransport(manager, true);
  assertStrictEquals(manager.getWsURL, configured);
});

Deno.test("run views keep Marimo transport URLs unchanged", () => {
  const manager = runtime();

  configureKioskTransport(manager, false);

  assertEquals(
    manager.getWsURL("session").toString(),
    "ws://example.test/base/ws?session_id=session",
  );
  assertEquals(
    manager.getSseURL("session").toString(),
    "https://example.test/base/sse?session_id=session",
  );
});
