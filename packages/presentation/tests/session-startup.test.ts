import { isSessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";
import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { RuntimeConfig } from "../src/runtime-config/index.ts";

import {
  bootstrapPresentationSession,
  PresentationDocumentRetiredError,
} from "../src/document/session-startup.ts";
import { symbolicRuntimeFields } from "./runtime-fixtures.ts";

const runtimeConfig = (revision: string): RuntimeConfig => ({
  schema: 1,
  revision,
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    data: {
      fileKey: "/workspace/analysis.py",
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession: true,
      url: "/",
    },
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  presentationSessionId: "s_view01",
  showCellLogs: true,
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
});

const wasmRuntimeConfig = (revision: string): RuntimeConfig => ({
  ...runtimeConfig(revision),
  runtime: {
    id: "wasm",
    instance: "wasm-instance",
    data: {
      code: "pass",
      filename: "analysis.py",
      version: "1",
      executionCells: [{ id: "bootstrap", code: "pass" }],
      bootstrapCellId: "bootstrap",
    },
  },
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

test("a fresh presentation session authorizes config before the native session resumes", async () => {
  const order: string[] = [];
  const nativeSessionId = "s_old123";
  assert.ok(isSessionId(nativeSessionId));
  const startup = await bootstrapPresentationSession({
    bootstrap: async (preflight) => {
      order.push("bootstrap");
      await preflight();
      order.push("native-session:s_old123");
      return nativeSessionId;
    },
    loadConfig: async (nativeSessionId) => {
      order.push(`load-config:${nativeSessionId ?? "preflight"}`);
      return runtimeConfig(nativeSessionId ?? "preflight");
    },
    replay: {
      pending: () => false,
      preflight: () => {
        order.push("session-preflight");
        return false;
      },
    },
    requiresSessionForConfig: false,
  });

  assert.deepEqual(order, [
    "bootstrap",
    "load-config:preflight",
    "session-preflight",
    "native-session:s_old123",
    "load-config:s_old123",
  ]);
  assert.equal(startup.config.revision, "s_old123");
});

test("WebAssembly startup keeps its preflight config", async () => {
  const loads: Array<string | undefined> = [];
  const sessionId = "s_wasm12";
  assert.ok(isSessionId(sessionId));

  const startup = await bootstrapPresentationSession({
    bootstrap: async (preflight) => {
      await preflight();
      return sessionId;
    },
    loadConfig: async (currentSessionId) => {
      loads.push(currentSessionId);
      return wasmRuntimeConfig("presentation-revision");
    },
    replay: {
      pending: () => false,
      preflight: () => false,
    },
    requiresSessionForConfig: false,
  });

  assert.deepEqual(loads, [undefined]);
  assert.equal(startup.config.runtime.id, "wasm");
});

test("document retirement between session bootstrap and config reload cancels startup", async () => {
  const controller = new AbortController();
  const retirement = new PresentationDocumentRetiredError();
  const loads: Array<string | undefined> = [];
  const sessionId = "s_retire";
  assert.ok(isSessionId(sessionId));

  const startup = bootstrapPresentationSession({
    bootstrap: async (preflight) => {
      await preflight();
      controller.abort(retirement);
      return sessionId;
    },
    loadConfig: async (currentSessionId) => {
      loads.push(currentSessionId);
      return runtimeConfig("presentation-revision");
    },
    replay: {
      pending: () => false,
      preflight: () => false,
    },
    requiresSessionForConfig: false,
    signal: controller.signal,
  });

  await assert.rejects(startup, (cause: unknown) => cause === retirement);
  assert.deepEqual(loads, [undefined]);
});

test("an active document reports config network failures", async () => {
  const failure = new TypeError("Failed to fetch");
  const sessionId = "s_live12";
  assert.ok(isSessionId(sessionId));
  const startup = bootstrapPresentationSession({
    bootstrap: async (preflight) => {
      await preflight();
      return sessionId;
    },
    loadConfig: () => Promise.reject(failure),
    replay: {
      pending: () => false,
      preflight: () => false,
    },
    requiresSessionForConfig: false,
    signal: new AbortController().signal,
  });

  await assert.rejects(startup, (cause: unknown) => cause === failure);
});
