import { describe, expect, test, vi } from "vite-plus/test";

const importOrder = vi.hoisted(() => [] as string[]);

vi.mock("../src/upstream/session.ts", () => {
  importOrder.push("session-module");
  return {
    getSessionId: () => {
      importOrder.push("get-session");
      return "s_abc123";
    },
  };
});

import { bootstrapSession, currentSessionId, isSessionId } from "../src/session-bootstrap.ts";

describe("Session bootstrap", () => {
  test("runs preflight before evaluating Marimo's session singleton", async () => {
    expect(importOrder).toEqual([]);
    expect(() => currentSessionId()).toThrow("has not been bootstrapped");

    const sessionId = await bootstrapSession(async () => {
      importOrder.push("preflight:start");
      await Promise.resolve();
      importOrder.push("preflight:complete");
    });

    expect(sessionId).toBe("s_abc123");
    expect(currentSessionId()).toBe("s_abc123");
    expect(importOrder).toEqual([
      "preflight:start",
      "preflight:complete",
      "session-module",
      "get-session",
    ]);
  });

  test("validates the pinned Marimo session identifier shape", () => {
    expect(isSessionId("s_abc123")).toBe(true);
    expect(isSessionId("s_ABC123")).toBe(false);
    expect(isSessionId("s_abc12")).toBe(false);
    expect(isSessionId(undefined)).toBe(false);
  });
});
