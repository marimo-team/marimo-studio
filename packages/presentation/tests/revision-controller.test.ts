import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { DocumentRevisionCommit } from "../src/document/revision-document.ts";
import type { RuntimeConfig } from "../src/runtime-config/index.ts";

import {
  PresentationRevisionController,
  type RevisionDocumentPort,
  type SessionReplayPort,
} from "../src/document/revision-controller.ts";
import { readiness } from "../src/readiness.ts";

const commit = (overrides: Partial<DocumentRevisionCommit> = {}): DocumentRevisionCommit => ({
  target: { documentUrl: "/report/", supportUrl: "/support/report" },
  supportChanged: false,
  reloadDocument: false,
  ...overrides,
});

const documentPort = (replace: RevisionDocumentPort["replace"]): RevisionDocumentPort => ({
  url: "/dashboard/",
  abort: vi.fn(),
  refreshStylesheets: vi.fn(async () => undefined),
  replace,
});

const options = () => ({
  applyRuntime: vi.fn(() => "applied" as const),
  reloadDocument: vi.fn(),
  reloadRuntime: vi.fn(),
  classifyFailure: vi.fn((cause: unknown) => ({
    state: "error" as const,
    diagnostic: {
      scope: "presentation" as const,
      code: "revision-failed",
      severity: "error" as const,
      message: String(cause),
      hint: "Fix the source.",
      view: "dashboard",
    },
  })),
  onFailure: vi.fn(),
  onReady: vi.fn(),
  onSupportChanged: vi.fn(),
});

const sessionReplay = (): SessionReplayPort => ({
  preservedUrl: vi.fn((target: string) => target),
  remember: vi.fn(),
});

test("a newer revision cancels and supersedes an in-flight transition", async () => {
  readiness.start();
  const signals: AbortSignal[] = [];
  let call = 0;
  const adapter = documentPort(async (_document, _support, signal) => {
    signals.push(signal);
    call += 1;
    if (call === 1) {
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), {
          once: true,
        });
      });
    }
    return commit();
  });
  const hooks = options();
  const controller = new PresentationRevisionController(
    adapter,
    "s_view01",
    hooks,
    sessionReplay(),
  );

  const first = controller.transition("/first/", "/support/first");
  await Promise.resolve();
  const second = controller.transition("/report/", "/support/report");

  assert.equal(await first, undefined);
  assert.deepEqual(await second, commit());
  assert.equal(signals[0]?.aborted, true);
  assert.equal(hooks.applyRuntime.mock.calls.length, 1);
  assert.equal(hooks.onReady.mock.calls.length, 1);
  assert.equal(readiness.snapshot().page, "connecting");
  assert.equal(readiness.snapshot().presentation, "ready");
});

test("a failed revision publishes one presentation failure", async () => {
  readiness.start();
  const error = new Error("invalid authored document");
  const adapter = documentPort(async () => {
    throw error;
  });
  const hooks = options();
  const controller = new PresentationRevisionController(
    adapter,
    "s_view01",
    hooks,
    sessionReplay(),
  );

  await assert.rejects(controller.transition("/report/", "/support/report"), error);

  assert.equal(readiness.snapshot().presentation, "error");
  assert.equal(readiness.snapshot().presentationDiagnostic?.code, "revision-failed");
  assert.deepEqual(hooks.onFailure.mock.calls[0]?.[0], error);
  assert.equal(hooks.onReady.mock.calls.length, 0);
});

test("a document reload bypasses the mounted runtime handoff", async () => {
  readiness.start();
  const target = { documentUrl: "/report/", supportUrl: "/support/report" };
  const adapter = documentPort(async () =>
    commit({ target, supportChanged: true, reloadDocument: true }),
  );
  const hooks = options();
  const controller = new PresentationRevisionController(
    adapter,
    "s_view01",
    hooks,
    sessionReplay(),
  );

  await controller.transition(target.documentUrl, target.supportUrl);

  assert.deepEqual(hooks.reloadDocument.mock.calls, [["/report/"]]);
  assert.equal(hooks.applyRuntime.mock.calls.length, 0);
  assert.equal(hooks.onSupportChanged.mock.calls.length, 0);
});

test("a committed support target reconnects its event source", async () => {
  readiness.start();
  const adapter = documentPort(async () => commit({ supportChanged: true }));
  const hooks = options();
  const controller = new PresentationRevisionController(
    adapter,
    "s_view01",
    hooks,
    sessionReplay(),
  );

  await controller.transition("/report/", "/support/report");

  assert.equal(hooks.onSupportChanged.mock.calls.length, 1);
  assert.equal(hooks.onReady.mock.calls.length, 1);
});
test("a runtime refresh can arrive before the initial config commits", async () => {
  readiness.start();
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "/_marimo-studio/views/dashboard",
    version: "test-version",
    revision: "presentation-revision",
    runtime: "wasm",
  };
  const config = {
    schema: 1,
    revision: "presentation-revision",
    view: "dashboard",
    views: ["dashboard"],
    runtime: {
      id: "wasm",
      instance: "wasm-instance",
      available: ["server", "wasm"],
      data: {},
    },
    rootUrl: "/",
    publicRootUrl: "/",
    documentRootUrl: "/dashboard/",
    supportUrl: "/_marimo-studio/views/dashboard",
    showCellLogs: true,
    cellBindings: {},
    valueBindings: {},
    outputBindings: {},
    diagnostics: [],
    appConfig: {},
    userConfig: {},
    configOverrides: {},
    dev: true,
    mode: "edit",
  } satisfies RuntimeConfig;
  const originalFetch = globalThis.fetch;
  let requestedRuntime: string | null = null;
  globalThis.fetch = (input) => {
    const url = new URL(input instanceof Request ? input.url : input);
    requestedRuntime = url.searchParams.get("runtime");
    return Promise.resolve(Response.json(config));
  };
  const hooks = options();
  const controller = new PresentationRevisionController(
    documentPort(async () => commit()),
    "s_view01",
    hooks,
    sessionReplay(),
  );

  try {
    await controller.refreshRuntime();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(requestedRuntime, "wasm");
  assert.equal(hooks.applyRuntime.mock.calls.length, 1);
  assert.equal(hooks.onReady.mock.calls.length, 1);
});
