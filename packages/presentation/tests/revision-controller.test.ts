import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { DocumentRevisionCommit } from "../src/document/revision-document.ts";

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
  replace,
});

const options = () => ({
  applyRuntime: vi.fn<() => "applied" | "pending" | "reload">(() => "applied"),
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

test("user navigation pushes history while presentation refresh replaces it", async () => {
  readiness.start();
  const histories: [string, string][] = [];
  const adapter = documentPort(
    async (_document, _support, _signal, _target, historyMode, historyUrl) => {
      histories.push([historyMode, historyUrl]);
      return commit();
    },
  );
  const controller = new PresentationRevisionController(adapter, options(), sessionReplay());

  await controller.navigate("/signed/report/", "/support/report", "/report/");
  await controller.transition("/report/", "/support/report");

  assert.deepEqual(histories, [
    ["push", "/report/"],
    ["replace", "/report/"],
  ]);
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
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());

  const first = controller.transition("/first/", "/support/first");
  const settled = controller.waitUntilIdle();
  await Promise.resolve();
  const second = controller.transition("/report/", "/support/report");

  assert.equal(await first, undefined);
  assert.deepEqual(await second, commit());
  assert.deepEqual(await settled, commit());
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
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());

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
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());

  await controller.transition(target.documentUrl, target.supportUrl);

  assert.deepEqual(hooks.reloadDocument.mock.calls, [["/report/"]]);
  assert.equal(hooks.applyRuntime.mock.calls.length, 0);
  assert.equal(hooks.onReady.mock.calls.length, 0);
  assert.equal(hooks.onSupportChanged.mock.calls.length, 0);
});

test("a navigation reload uses its public history URL", async () => {
  readiness.start();
  const adapter = documentPort(async () =>
    commit({
      target: { documentUrl: "/signed/report/", supportUrl: "/support/report" },
      reloadDocument: true,
    }),
  );
  const hooks = options();
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());

  await controller.navigate("/signed/report/", "/support/report", "/report/");

  assert.deepEqual(hooks.reloadDocument.mock.calls, [["/report/"]]);
  assert.equal(hooks.applyRuntime.mock.calls.length, 0);
});

test("a runtime reload leaves readiness to the replacement document", async () => {
  readiness.start();
  const adapter = documentPort(async () => commit());
  const hooks = options();
  hooks.applyRuntime.mockReturnValue("reload");
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());

  await controller.transition("/report/", "/support/report");

  assert.equal(hooks.reloadRuntime.mock.calls.length, 1);
  assert.equal(hooks.onReady.mock.calls.length, 0);
});

test("a committed support target reconnects its event source", async () => {
  readiness.start();
  const adapter = documentPort(async () => commit({ supportChanged: true }));
  const hooks = options();
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());

  await controller.transition("/report/", "/support/report");

  assert.equal(hooks.onSupportChanged.mock.calls.length, 1);
  assert.equal(hooks.onReady.mock.calls.length, 1);
});
