import {
  classifyProjectedOutputFunctionRequest,
  disposeProjectedOutputFunctionGate,
  PROJECTED_OUTPUT_FUNCTION_DRAIN_TIMEOUT_MS,
  PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE,
  PROJECTED_OUTPUT_OWNER_ATTRIBUTE,
  PROJECTED_OUTPUT_SCOPE_ATTRIBUTE,
  runProjectedOutputFunctionRequest,
  startProjectedOutputFunctionGate,
} from "@marimo-studio/marimo-frontend/projected-output-function-gate";
import assert from "node:assert/strict";
import { test, vi } from "vite-plus/test";

import type { DocumentRevisionCommit } from "../src/document/revision-document.ts";

import {
  PresentationRevisionController,
  type PresentationRevisionPolicy,
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
  classifyFailure: vi.fn<PresentationRevisionPolicy["classifyFailure"]>((cause: unknown) => ({
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

const projectedCaller = () => {
  const wrapper = document.createElement("div");
  wrapper.setAttribute(PROJECTED_OUTPUT_SCOPE_ATTRIBUTE, "");
  wrapper.setAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, "revision-a");
  wrapper.setAttribute(PROJECTED_OUTPUT_OWNER_ATTRIBUTE, "revision-a");
  const element = document.createElement("marimo-table");
  wrapper.append(element);
  document.body.append(wrapper);
  return { element, wrapper };
};

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

test("a revision transition pauses projected function requests before document work", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  let finishDocument = () => {};
  const documentWork = new Promise<void>((resolve) => {
    finishDocument = resolve;
  });
  const adapter = documentPort(async () => {
    await documentWork;
    return commit();
  });
  const controller = new PresentationRevisionController(adapter, options(), sessionReplay());
  const send = vi.fn(async () => "sent");

  try {
    const transition = controller.transition("/report/", "/support/report");
    const request = runProjectedOutputFunctionRequest(element, send);
    assert.equal(send.mock.calls.length, 0);

    finishDocument();
    await transition;
    assert.equal(await request, "sent");
    assert.equal(send.mock.calls.length, 1);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("a revision transition drains admitted function requests before document work", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  let resolveAdmission = (_result: string) => {};
  const admission = new Promise<string>((resolve) => {
    resolveAdmission = resolve;
  });
  const request = runProjectedOutputFunctionRequest(element, () =>
    classifyProjectedOutputFunctionRequest(admission),
  );
  let documentStarted = false;
  const controller = new PresentationRevisionController(
    documentPort(async () => {
      documentStarted = true;
      return commit();
    }),
    options(),
    sessionReplay(),
  );

  try {
    const transition = controller.transition("/report/", "/support/report");
    await Promise.resolve();
    assert.equal(documentStarted, false);
    resolveAdmission("admitted");
    await transition;
    assert.equal(documentStarted, true);
    assert.equal(await request, "admitted");
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("cancelling a revision terminates a stalled function admission drain", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  const admission = new Promise<string>(() => {});
  const request = runProjectedOutputFunctionRequest(element, () =>
    classifyProjectedOutputFunctionRequest(admission),
  );
  const rejected = assert.rejects(request, { name: "AbortError" });
  let documentStarted = false;
  const controller = new PresentationRevisionController(
    documentPort(async () => {
      documentStarted = true;
      return commit();
    }),
    options(),
    sessionReplay(),
  );

  try {
    const transition = controller.transition("/report/", "/support/report");
    await Promise.resolve();
    assert.equal(documentStarted, false);
    controller.dispose();
    assert.equal(await transition, undefined);
    await rejected;
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("a stalled function admission keeps the current document at the drain deadline", async () => {
  vi.useFakeTimers();
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  const admission = new Promise<string>(() => {});
  const request = runProjectedOutputFunctionRequest(element, () =>
    classifyProjectedOutputFunctionRequest(admission),
  );
  const rejected = assert.rejects(request, { name: "AbortError" });
  let documentStarted = false;
  const controller = new PresentationRevisionController(
    documentPort(async () => {
      documentStarted = true;
      return commit();
    }),
    options(),
    sessionReplay(),
  );

  try {
    const transition = controller.transition("/report/", "/support/report");
    const timedOut = assert.rejects(transition, {
      name: "ProjectedOutputFunctionDrainTimeoutError",
    });
    await vi.advanceTimersByTimeAsync(PROJECTED_OUTPUT_FUNCTION_DRAIN_TIMEOUT_MS);
    await timedOut;
    assert.equal(documentStarted, false);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
    await rejected;
    vi.useRealTimers();
  }
});

test("a transient revision failure holds projected function requests until retry", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  const failure = new Error("revision is still publishing");
  let attempt = 0;
  const adapter = documentPort(async () => {
    attempt += 1;
    if (attempt === 1) {
      throw failure;
    }
    return commit();
  });
  const hooks = options();
  hooks.classifyFailure.mockReturnValue({
    state: "loading",
    diagnostic: {
      scope: "presentation",
      code: "presentation-revision-mismatch",
      severity: "warning",
      message: "The revision is still publishing.",
      hint: "Retry after publication finishes.",
      view: "dashboard",
    },
  });
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());
  const send = vi.fn(async () => "sent");

  try {
    const first = controller.transition("/report/", "/support/report");
    const request = runProjectedOutputFunctionRequest(element, send);
    await assert.rejects(first, failure);
    assert.equal(send.mock.calls.length, 0);

    await controller.transition("/report/", "/support/report");
    assert.equal(await request, "sent");
    assert.equal(send.mock.calls.length, 1);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("disposing a transient revision failure cancels its projected function requests", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  const failure = new Error("revision is still publishing");
  const hooks = options();
  hooks.classifyFailure.mockReturnValue({
    state: "loading",
    diagnostic: {
      scope: "presentation",
      code: "runtime-sync-pending",
      severity: "warning",
      message: "The runtime is still publishing.",
      hint: "Retry after publication finishes.",
      view: "dashboard",
    },
  });
  const controller = new PresentationRevisionController(
    documentPort(async () => {
      throw failure;
    }),
    hooks,
    sessionReplay(),
  );
  const send = vi.fn(async () => "sent");

  try {
    const transition = controller.transition("/report/", "/support/report");
    const request = runProjectedOutputFunctionRequest(element, send);
    const cancelled = assert.rejects(request, { name: "AbortError" });
    await assert.rejects(transition, failure);
    controller.dispose();
    await cancelled;
    assert.equal(send.mock.calls.length, 0);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("a document reload cancels paused projected function requests", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  let finishDocument = () => {};
  const documentWork = new Promise<void>((resolve) => {
    finishDocument = resolve;
  });
  const adapter = documentPort(async () => {
    await documentWork;
    return commit({ reloadDocument: true });
  });
  const hooks = options();
  const controller = new PresentationRevisionController(adapter, hooks, sessionReplay());
  const send = vi.fn(async () => "sent");

  try {
    const transition = controller.transition("/report/", "/support/report");
    const request = runProjectedOutputFunctionRequest(element, send);
    const rejected = assert.rejects(request, { name: "AbortError" });
    finishDocument();

    await transition;
    await rejected;
    assert.equal(send.mock.calls.length, 0);
    assert.equal(hooks.reloadDocument.mock.calls.length, 1);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("a failed document reload resumes the retained projected function owner", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  const failure = new Error("document reload failed");
  const hooks = options();
  hooks.reloadDocument.mockImplementation(() => {
    throw failure;
  });
  const controller = new PresentationRevisionController(
    documentPort(async () => commit({ reloadDocument: true })),
    hooks,
    sessionReplay(),
  );
  const send = vi.fn(async () => "sent");

  try {
    const transition = controller.transition("/report/", "/support/report");
    const request = runProjectedOutputFunctionRequest(element, send);
    await assert.rejects(transition, failure);
    assert.equal(await request, "sent");
    assert.equal(send.mock.calls.length, 1);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
});

test("a failed runtime reload resumes the retained projected function owner", async () => {
  readiness.start();
  const gate = startProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedCaller();
  const failure = new Error("runtime reload failed");
  const hooks = options();
  hooks.applyRuntime.mockReturnValue("reload");
  hooks.reloadRuntime.mockImplementation(() => {
    throw failure;
  });
  const controller = new PresentationRevisionController(
    documentPort(async () => commit()),
    hooks,
    sessionReplay(),
  );
  const send = vi.fn(async () => "sent");

  try {
    const transition = controller.transition("/report/", "/support/report");
    const request = runProjectedOutputFunctionRequest(element, send);
    await assert.rejects(transition, failure);
    assert.equal(await request, "sent");
    assert.equal(send.mock.calls.length, 1);
  } finally {
    controller.dispose();
    client.dispose();
    disposeProjectedOutputFunctionGate(gate);
    wrapper.remove();
  }
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
