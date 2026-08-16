// @vitest-environment jsdom

import { describe, expect, test, vi } from "vite-plus/test";

import { createSessionBootstrap } from "../src/session-bootstrap-core.ts";
import { bootstrapSession, currentSessionId, isSessionId } from "../src/session-bootstrap.ts";

describe("Session bootstrap", () => {
  test("runs preflight before evaluating Marimo's session singleton", async () => {
    const importOrder = new Array<string>();
    const session = createSessionBootstrap(async () => {
      importOrder.push("session-module");
      return "s_abc123";
    });

    expect(importOrder).toEqual([]);
    expect(() => session.current()).toThrow("has not been bootstrapped");

    const sessionId = await session.bootstrap(async () => {
      importOrder.push("preflight:start");
      await Promise.resolve();
      importOrder.push("preflight:complete");
    });

    expect(sessionId).toBe("s_abc123");
    expect(session.current()).toBe("s_abc123");
    expect(importOrder).toEqual(["preflight:start", "preflight:complete", "session-module"]);
  });

  test("validates the pinned Marimo session identifier shape", () => {
    expect(isSessionId("s_abc123")).toBe(true);
    expect(isSessionId("s_ABC123")).toBe(false);
    expect(isSessionId("s_abc12")).toBe(false);
    expect(isSessionId(undefined)).toBe(false);
  });

  test("loads Marimo's session after preflight", async () => {
    window.history.replaceState({}, "", "?session_id=s_abc123");

    expect(() => currentSessionId()).toThrow("has not been bootstrapped");

    const preflight = vi.fn();
    const sessionId = await bootstrapSession(preflight);

    expect(preflight).toHaveBeenCalledOnce();
    expect(sessionId).toBe("s_abc123");
    expect(currentSessionId()).toBe(sessionId);
  });
});
