import { isSessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";
import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { RuntimeConfig } from "../src/runtime-config/index.ts";

import { bootstrapPresentationSession } from "../src/document/session-startup.ts";

const runtimeConfig = (revision: string): RuntimeConfig => ({
  schema: 1,
  revision,
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server"],
    data: {
      fileKey: "/workspace/analysis.py",
      serverToken: "token",
      preserveSession: true,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  showCellLogs: true,
  cellBindings: {},
  valueBindings: {},
  outputBindings: {},
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
});

test("a preserved session preflights and reloads configuration before runtime composition", async () => {
  const order: string[] = [];
  const sessionId = "s_abc123";
  assert.ok(isSessionId(sessionId));

  const startup = await bootstrapPresentationSession({
    bootstrap: async (preflight) => {
      order.push("bootstrap");
      await preflight();
      order.push("marimo-session-module");
      return sessionId;
    },
    loadConfig: async (currentSessionId) => {
      order.push(`load-config:${currentSessionId ?? "preflight"}`);
      return runtimeConfig(currentSessionId ? "connected" : "preflight");
    },
    replay: {
      pending: () => true,
      preflight: () => {
        order.push("session-preflight");
        return true;
      },
    },
    requiresSessionForConfig: false,
  });

  assert.deepEqual(order, [
    "bootstrap",
    "load-config:preflight",
    "session-preflight",
    "marimo-session-module",
    "load-config:s_abc123",
  ]);
  assert.equal(startup.sessionId, sessionId);
  assert.equal(startup.config.revision, "connected");
  assert.equal(startup.replaying, true);
});
