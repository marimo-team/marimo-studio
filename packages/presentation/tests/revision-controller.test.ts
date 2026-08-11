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
  loadRevision: vi.fn(
    async (config: RuntimeConfig, _previewSessionId: string, _signal: AbortSignal) => config,
  ),
  reloadDocument: vi.fn(),
  reloadRuntime: vi.fn(),
  classifyFailure: vi.fn((error: unknown) => ({
    state: "error" as const,
    diagnostic: {
      scope: "presentation" as const,
      code: "revision-failed",
      severity: "error" as const,
      message: String(error),
      hint: "Fix the source.",
      view: "dashboard",
    },
  })),
  onFailure: vi.fn(),
  onReady: vi.fn(),
  onSupportChanged: vi.fn(),
});

const sessionReplay = (): SessionReplayPort => ({
  prepare: vi.fn(() => false),
  preservedUrl: vi.fn((target: string) => target),
  finish: vi.fn(),
  remember: vi.fn(),
});

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

test("the revision transaction owns session replay completion", async () => {
  readiness.start();
  const adapter = documentPort(async () => commit());
  const hooks = options();
  const replay = sessionReplay();
  vi.mocked(replay.prepare).mockReturnValue(true);
  vi.mocked(hooks.loadRevision).mockResolvedValue(runtimeConfig("revision-2"));
  const controller = new PresentationRevisionController(adapter, "s_view01", hooks, replay);

  const resumed = await controller.resume(runtimeConfig("revision-1"));
  document.dispatchEvent(new CustomEvent("marimo-studio:runtime-ready"));

  assert.equal(resumed.revision, "revision-2");
  assert.equal(hooks.loadRevision.mock.calls[0]?.[1], "s_view01");
  assert.equal(vi.mocked(replay.finish).mock.calls.length, 1);
  assert.equal(readiness.snapshot().presentation, "ready");
});
