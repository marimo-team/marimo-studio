import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { DocumentRevisionCommit } from "../src/document/revision-document.ts";

import {
  PresentationRevisionController,
  type RevisionDocumentPort,
  type SessionReplayPort,
} from "../src/document/revision-controller.ts";
import { readiness } from "../src/readiness.ts";
import { wasmRuntime } from "../src/runtime/catalog.ts";

const finishCommit = () => {};
const rollbackCommit = () => {};
const commit = (overrides: Partial<DocumentRevisionCommit> = {}): DocumentRevisionCommit => ({
  target: { documentUrl: "/report/", supportUrl: "/support/report" },
  supportChanged: false,
  reloadDocument: false,
  finish: finishCommit,
  rollback: rollbackCommit,
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

test("a document replacement waits for the runtime operation barrier", async () => {
  readiness.start();
  let releaseRuntime = () => {};
  const runtimeReady = new Promise<void>((resolve) => {
    releaseRuntime = resolve;
  });
  const replace = vi.fn(async () => commit());
  const adapter = documentPort(replace);
  const hooks = options();
  hooks.beginRuntimeRevision.mockImplementation(async (signal) => {
    await runtimeReady;
    return {
      apply: async () => await hooks.applyRuntime(signal),
      commit: vi.fn(async () => {}),
      rollback: vi.fn(async () => {}),
    };
  });
  const controller = new PresentationRevisionController(
    adapter,
    "s_view01",
    hooks,
    sessionReplay(),
  );

  const transitioning = controller.transition("/report/", "/support/report");
  await vi.waitFor(() => assert.equal(hooks.beginRuntimeRevision.mock.calls.length, 1));
  assert.equal(replace.mock.calls.length, 0);
  releaseRuntime();
  await transitioning;

  assert.equal(replace.mock.calls.length, 1);
});

test("a superseding revision waits for the cancelled runtime update before swapping DOM", async () => {
  readiness.start();
  let shell = "initial";
  let staleMutation = false;
  let finishCancelledUpdate = () => {};
  const replacement = vi.fn(async (documentUrl: string) => {
    if (documentUrl === "/revision-b/") {
      shell = "revision-b";
      throw new Error("revision B failed");
    }
    shell = "revision-a";
    return commit({ target: { documentUrl, supportUrl: "/support/a" } });
  });
  const hooks = options();
  hooks.applyRuntime.mockImplementationOnce(
    async (signal: AbortSignal) =>
      await new Promise<"applied">((_resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => {
            finishCancelledUpdate = () => {
              staleMutation = shell !== "revision-a";
              reject(signal.reason);
            };
          },
          { once: true },
        );
      }),
  );
  const controller = new PresentationRevisionController(
    documentPort(replacement),
    "s_view01",
    hooks,
    sessionReplay(),
  );

  const revisionA = controller.transition("/revision-a/", "/support/a");
  await vi.waitFor(() => assert.equal(hooks.applyRuntime.mock.calls.length, 1));
  const revisionB = controller.transition("/revision-b/", "/support/b");
  await Promise.resolve();
  assert.equal(replacement.mock.calls.length, 1);
  assert.equal(shell, "revision-a");
  finishCancelledUpdate();

  assert.equal(await revisionA, undefined);
  await assert.rejects(revisionB, /revision B failed/);
  assert.equal(staleMutation, false);
  assert.equal(shell, "revision-b");
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

test("a revision stays loading until its runtime update commits", async () => {
  readiness.start();
  let finishRuntime = (_result: "applied") => {};
  const runtimeUpdate = new Promise<"applied">((resolve) => {
    finishRuntime = resolve;
  });
  const hooks = options();
  hooks.applyRuntime.mockReturnValue(runtimeUpdate);
  const controller = new PresentationRevisionController(
    documentPort(async () => commit()),
    "s_view01",
    hooks,
    sessionReplay(),
  );

  const transitioning = controller.transition("/report/", "/support/report");
  await vi.waitFor(() => assert.equal(hooks.applyRuntime.mock.calls.length, 1));

  assert.equal(readiness.snapshot().presentation, "loading");
  assert.equal(hooks.onReady.mock.calls.length, 0);
  finishRuntime("applied");
  await transitioning;

  assert.equal(readiness.snapshot().presentation, "ready");
  assert.equal(hooks.onReady.mock.calls.length, 1);
});

test("a failed runtime update keeps the revision from publishing ready", async () => {
  readiness.start();
  let failRuntime = (_error: Error) => {};
  const runtimeUpdate = new Promise<"applied">((_resolve, reject) => {
    failRuntime = reject;
  });
  const hooks = options();
  hooks.applyRuntime.mockReturnValue(runtimeUpdate);
  const controller = new PresentationRevisionController(
    documentPort(async () => commit()),
    "s_view01",
    hooks,
    sessionReplay(),
  );
  const error = new Error("prepared publication failed");

  const transitioning = controller.transition("/report/", "/support/report");
  await vi.waitFor(() => assert.equal(hooks.applyRuntime.mock.calls.length, 1));
  assert.equal(readiness.snapshot().presentation, "loading");
  failRuntime(error);
  await assert.rejects(transitioning, error);

  assert.equal(readiness.snapshot().presentation, "error");
  assert.equal(hooks.onReady.mock.calls.length, 0);
  assert.deepEqual(hooks.onFailure.mock.calls[0]?.[0], error);
});

test("a failed runtime update rolls back the coupled document and runtime state", async () => {
  readiness.start();
  const state = {
    config: "A",
    controls: "A",
    dom: "A",
    publication: "A",
    styles: "A",
    url: "/a/",
  };
  const rollbackDocument = vi.fn(() => {
    state.config = "A";
    state.dom = "A";
    state.styles = "A";
    state.url = "/a/";
  });
  const adapter = documentPort(async () => {
    state.config = "B";
    state.dom = "B";
    state.styles = "B";
    state.url = "/b/";
    return commit({ rollback: rollbackDocument });
  });
  const rollbackRuntime = vi.fn(async () => {
    state.controls = "A";
    state.publication = "A";
  });
  const hooks = options();
  hooks.beginRuntimeRevision.mockResolvedValue({
    apply: async () => {
      state.controls = "B";
      state.publication = "B";
      throw new Error("runtime B failed");
    },
    commit: vi.fn(async () => {}),
    rollback: rollbackRuntime,
  });
  const controller = new PresentationRevisionController(
    adapter,
    "s_view01",
    hooks,
    sessionReplay(),
  );

  await assert.rejects(controller.transition("/b/", "/support/b"), /runtime B failed/);

  assert.deepEqual(state, {
    config: "A",
    controls: "A",
    dom: "A",
    publication: "A",
    styles: "A",
    url: "/a/",
  });
  assert.equal(rollbackDocument.mock.calls.length, 1);
  assert.equal(rollbackRuntime.mock.calls.length, 1);
});

test("a revision attempts document and runtime rollback after independent failures", async () => {
  readiness.start();
  const primary = new Error("runtime apply failed");
  const documentFailure = new Error("document rollback failed");
  const runtimeFailure = new Error("runtime rollback failed");
  const rollbackDocument = vi.fn(() => {
    throw documentFailure;
  });
  const rollbackRuntime = vi.fn(async () => {
    throw runtimeFailure;
  });
  const hooks = options();
  hooks.beginRuntimeRevision.mockResolvedValue({
    apply: async () => {
      throw primary;
    },
    commit: vi.fn(async () => {}),
    rollback: rollbackRuntime,
  });
  const controller = new PresentationRevisionController(
    documentPort(async () => commit({ rollback: rollbackDocument })),
    "s_view01",
    hooks,
    sessionReplay(),
  );

  let failure: unknown;
  try {
    await controller.transition("/b/", "/support/b");
  } catch (error) {
    failure = error;
  }

  if (!(failure instanceof AggregateError)) {
    throw new TypeError("Expected revision rollback failures to be aggregated");
  }
  assert.deepEqual(failure.errors.slice(0, 3), [primary, documentFailure, runtimeFailure]);
  assert.equal(rollbackDocument.mock.calls.length, 1);
  assert.equal(rollbackRuntime.mock.calls.length, 1);
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
