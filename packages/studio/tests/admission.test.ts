import type { BrowserDiagnostic } from "@marimo-studio/protocol/browser-observations";

import { expect, it, vi } from "vite-plus/test";

import {
  PreviewAdmission,
  type PreviewAdmissionEffects,
} from "../src/features/preview/admission.ts";

const diagnostic: BrowserDiagnostic = {
  code: "presentation-waiting",
  severity: "warning",
  message: "The presentation is waiting.",
  hint: "Wait for the current revision.",
  view: "dashboard",
  scope: "presentation",
};

const projectionDiagnostic: BrowserDiagnostic = {
  code: "projection-missing",
  severity: "error",
  message: "The projected value is missing.",
  hint: "Restore the value in the notebook.",
  view: "dashboard",
  scope: "projection",
  projection: "value",
  target: "user_note",
};

const createAdmission = () => {
  const effects = {
    clearObservations: vi.fn(),
    clearSession: vi.fn(),
    failView: vi.fn(),
    localizedInteractive: vi.fn(),
    postMessage: vi.fn(),
    postObservations: vi.fn(),
    postSwitch: vi.fn(),
    ready: vi.fn(),
    observation: vi.fn(),
    status: vi.fn(),
    stopControls: vi.fn(),
    viewFailed: vi.fn(),
  } satisfies PreviewAdmissionEffects;
  return { admission: new PreviewAdmission(effects), effects };
};

const admitted = (revision = "revision-1") => {
  const owner = createAdmission();
  owner.admission.receiverReady(revision, "current", "active");
  owner.admission.viewReady(revision, "s_123456", "active");
  return owner;
};

it("admits and commits one exact receiver revision", () => {
  const { admission, effects } = createAdmission();

  admission.receiverReady("revision-1", "current", "active");
  expect(admission.receiverReadyForCurrentView).toBe(true);
  admission.viewReady("revision-1", "s_123456", "active");

  expect(admission.isReady).toBe(true);
  expect(admission.identity).toEqual({ revision: "revision-1", sessionId: "s_123456" });
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:receiver-admitted",
    revision: "revision-1",
  });
  expect(effects.ready).toHaveBeenCalledWith({
    revision: "revision-1",
    sessionId: "s_123456",
  });
});

it("keeps another view receiver unmatched through target baseline ordering", () => {
  const { admission, effects } = createAdmission();

  admission.receiverReady("other-revision", "other", "active");
  expect(admission.receiverPresent).toBe(true);
  expect(admission.receiverReadyForCurrentView).toBe(false);
  expect(admission.snapshot.receiver).toEqual({ phase: "ready-unmatched" });
  expect(effects.postSwitch).toHaveBeenCalledOnce();

  admission.presentationBaseline("target-revision", "active");
  admission.buildCompleted("target-revision", "active");
  expect(effects.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:presentation-change" }),
  );
  expect(effects.postMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "marimo-studio:receiver-admitted" }),
  );

  admission.viewReady("target-revision", null, "active");
  expect(admission.isReady).toBe(true);
});

it("holds cached readiness behind a changed build and fresh admission", () => {
  const { admission, effects } = admitted("revision-old");
  effects.postMessage.mockClear();

  admission.buildStarted("active");
  expect(admission.isReady).toBe(false);
  expect(admission.snapshot.candidate?.revision).toBe("revision-old");
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-refresh",
    phase: "pending",
  });

  admission.buildCompleted("revision-new", "active");
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });
  admission.receiverUnready();
  admission.receiverReady("revision-new", "current", "active");
  admission.viewReady("revision-new", "s_new123", "active");
  expect(admission.isReady).toBe(true);
});

it("reuses a cached candidate only after a same-revision build settles", () => {
  const { admission, effects } = admitted();
  effects.ready.mockClear();

  admission.buildStarted("active");
  admission.buildCompleted("revision-1", "active");

  expect(admission.isReady).toBe(true);
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-refresh",
    phase: "settled",
  });
  expect(effects.ready).toHaveBeenCalledOnce();
});

it("recovers a ready view after an unchanged transaction retry", () => {
  const { admission, effects } = admitted();
  effects.ready.mockClear();

  admission.buildStarted("active", false);
  admission.mutationError(diagnostic, "revision-1");
  expect(admission.snapshot.view).toBe("failed");

  expect(admission.buildUnchanged("active")).toBe(true);
  expect(admission.isReady).toBe(true);
  expect(effects.ready).toHaveBeenCalledOnce();
});

it("keeps a disconnected receiver unready after an unchanged transaction", () => {
  const { admission, effects } = admitted();
  effects.ready.mockClear();

  admission.buildStarted("active");
  admission.receiverUnready();
  expect(admission.buildUnchanged("active")).toBe(true);

  expect(admission.isReady).toBe(false);
  expect(admission.snapshot).toMatchObject({
    candidate: null,
    receiver: { phase: "unready" },
    view: "waiting",
  });
  expect(effects.ready).not.toHaveBeenCalled();
});

it("keeps newer presentation and view failures after an unchanged transaction", () => {
  const changed = admitted();
  changed.effects.ready.mockClear();
  changed.admission.buildStarted("active", false);
  changed.admission.presentationChanged("revision-2", "active");
  changed.admission.mutationError(diagnostic, "revision-1");
  changed.admission.buildUnchanged("active");
  expect(changed.admission.isReady).toBe(false);
  expect(changed.admission.snapshot.presentation.refresh).toBe("requested");
  expect(changed.effects.ready).not.toHaveBeenCalled();
  expect(changed.effects.viewFailed).not.toHaveBeenCalled();

  const failed = admitted();
  failed.effects.ready.mockClear();
  failed.admission.buildStarted("active", false);
  failed.admission.mutationError(diagnostic, "revision-1");
  expect(failed.admission.isInteractive).toBe(false);
  failed.admission.viewError(diagnostic, "revision-1", "active");
  failed.admission.buildUnchanged("active");
  expect(failed.admission.snapshot.view).toBe("failed");
  expect(failed.effects.ready).not.toHaveBeenCalled();
});

it("preserves an external failure when a mutation failure arrives later", () => {
  const { admission, effects } = admitted();
  const external = { ...diagnostic, code: "external-view-failure" };
  admission.buildStarted("active", false);
  admission.viewError(external, "revision-1", "active");

  admission.mutationError(diagnostic, "revision-1");
  admission.buildUnchanged("active");

  expect(admission.snapshot.view).toBe("failed");
  expect(effects.viewFailed).toHaveBeenCalledOnce();
  expect(effects.viewFailed).toHaveBeenCalledWith(external, "revision-1");
});

it("keeps an unknown baseline non-ready after a mutation retry", () => {
  const { admission, effects } = admitted();
  effects.ready.mockClear();
  admission.buildStarted("active", false);
  admission.mutationError(diagnostic, "revision-1");

  admission.presentationBaseline(null, "active");
  admission.buildUnchanged("active");

  expect(admission.isReady).toBe(false);
  expect(admission.snapshot.candidate).toBeNull();
  expect(effects.ready).not.toHaveBeenCalled();
});

it("keeps a mutation failure after its presentation stream is abandoned", () => {
  const { admission, effects } = admitted();
  effects.ready.mockClear();
  admission.buildStarted("active", false);
  admission.mutationError(diagnostic, "revision-1");

  admission.streamAbandoned();
  admission.presentationBaseline("revision-1", "active");

  expect(admission.snapshot.view).toBe("failed");
  expect(admission.snapshot.candidate).toBeNull();
  expect(effects.ready).not.toHaveBeenCalled();
});

it("preserves failed and connecting views across unchanged transactions", () => {
  const failed = admitted();
  failed.admission.viewError(diagnostic, "revision-1", "active");
  failed.effects.stopControls.mockClear();
  failed.effects.clearObservations.mockClear();
  failed.admission.buildStarted("active");
  expect(failed.effects.stopControls).toHaveBeenCalledOnce();
  expect(failed.effects.clearObservations).toHaveBeenCalledOnce();
  failed.admission.buildUnchanged("active");
  expect(failed.admission.snapshot.view).toBe("failed");

  const connecting = createAdmission();
  connecting.admission.buildStarted("active");
  expect(connecting.effects.stopControls).toHaveBeenCalledOnce();
  expect(connecting.effects.clearObservations).toHaveBeenCalledOnce();
  connecting.admission.buildUnchanged("active");
  expect(connecting.admission.snapshot).toMatchObject({
    receiver: { phase: "unready" },
    view: "waiting",
  });
  expect(connecting.effects.ready).not.toHaveBeenCalled();
});

it("requires a warm active document to refresh before it is ready again", () => {
  const { admission, effects } = admitted();
  effects.postMessage.mockClear();

  admission.reactivate("active");

  expect(admission.isReady).toBe(false);
  expect(admission.snapshot.presentation.refresh).toBe("requested");
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });

  admission.viewReady("revision-1", "s_123456", "active");
  expect(admission.isReady).toBe(false);
  admission.receiverUnready();
  admission.receiverUnready();
  expect(admission.snapshot.presentation.refresh).toBe("acknowledged");
  admission.receiverReady("revision-1", "current", "active");
  admission.viewReady("revision-1", "s_123456", "active");
  expect(admission.isReady).toBe(true);
});

it("preserves exact warm readiness when the authoritative baseline matches", () => {
  const { admission, effects } = admitted();
  admission.presentationBaseline("revision-1", "inactive");
  effects.postMessage.mockClear();

  admission.reactivate("active");

  expect(admission.isReady).toBe(true);
  expect(effects.postMessage).not.toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });
});

it("revokes warm readiness when an authoritative baseline differs", () => {
  const { admission, effects } = admitted();
  admission.presentationBaseline("revision-2", "inactive");
  expect(admission.isReady).toBe(false);
  effects.postMessage.mockClear();

  admission.reactivate("active");

  expect(admission.isReady).toBe(false);
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });
});

it("settles a stream-owned build barrier when its stream is abandoned", () => {
  const { admission, effects } = admitted();
  admission.buildStarted("active");
  effects.postMessage.mockClear();

  admission.streamAbandoned(true);

  expect(admission.snapshot.presentation).toMatchObject({
    baseline: { phase: "unknown" },
    build: "settled",
    gate: "settled",
    refresh: "required",
  });
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-refresh",
    phase: "settled",
  });
});

it("accepts terminal ready after loading for the same admitted observation", () => {
  const { admission, effects } = admitted();
  effects.observation.mockClear();

  admission.observation("loading", [diagnostic], "revision-1", "s_123456");
  expect(admission.viewIsReady).toBe(false);
  admission.observation("ready", [], "revision-1", "s_123456");

  expect(admission.viewIsReady).toBe(true);
  expect(effects.observation.mock.calls.map(([phase]) => phase)).toEqual([
    "synchronizing",
    "ready",
  ]);
});

it("retains view admission after a localized observation error", () => {
  const { admission, effects } = admitted();
  effects.observation.mockClear();

  admission.observation("loading", [], "revision-1", "s_123456");
  admission.observation("error", [projectionDiagnostic], "revision-1", "s_123456");

  expect(admission.snapshot.view).toBe("failed");
  expect(admission.isReady).toBe(false);
  expect(admission.isInteractive).toBe(true);
  expect(effects.observation.mock.calls.map(([phase]) => phase)).toEqual([
    "synchronizing",
    "failed",
  ]);

  admission.viewError(diagnostic, "revision-1", "active");
  expect(admission.isInteractive).toBe(false);
});

it("keeps an exact projection view error interactive", () => {
  const { admission, effects } = admitted();

  admission.viewError(projectionDiagnostic, "revision-1", "active");

  expect(admission.snapshot.view).toBe("failed");
  expect(admission.isReady).toBe(false);
  expect(admission.isInteractive).toBe(true);
  expect(effects.viewFailed).toHaveBeenCalledWith(projectionDiagnostic, "revision-1");
  expect(effects.localizedInteractive).not.toHaveBeenCalled();
  expect(effects.failView).not.toHaveBeenCalled();
});

it.each([
  ["session-bearing", "s_error2"],
  ["sessionless", null],
] as const)("latches a %s local error until its build is admitted", (_kind, sessionId) => {
  const { admission, effects } = createAdmission();
  admission.buildStarted("active");
  admission.receiverReady("revision-2", "current", "active");

  admission.viewError(projectionDiagnostic, "revision-2", "active", sessionId);

  expect(admission.identity).toEqual({ revision: "revision-2", sessionId });
  expect(admission.isInteractive).toBe(false);

  admission.buildCompleted("revision-2", "active");
  expect(admission.isReady).toBe(false);
  expect(admission.isInteractive).toBe(true);
  expect(effects.localizedInteractive).toHaveBeenCalledOnce();
  expect(effects.localizedInteractive).toHaveBeenCalledWith({
    revision: "revision-2",
    sessionId,
  });
});

it("does not invent a session for a local error before view readiness", () => {
  const { admission, effects } = createAdmission();
  admission.buildStarted("active");
  admission.receiverReady("revision-2", "current", "active");

  admission.viewError(projectionDiagnostic, "revision-2", "active");
  admission.buildCompleted("revision-2", "active");

  expect(admission.identity).toBeNull();
  expect(admission.isInteractive).toBe(false);
  expect(effects.failView).toHaveBeenCalledOnce();
});

it.each(["runtime", "presentation"])("keeps an exact %s view error noninteractive", (scope) => {
  const { admission, effects } = admitted();
  effects.stopControls.mockClear();

  admission.viewError({ ...diagnostic, scope }, "revision-1", "active");

  expect(admission.isInteractive).toBe(false);
  expect(effects.stopControls).toHaveBeenCalledOnce();
  expect(effects.failView).toHaveBeenCalledOnce();
});

it("keeps projection errors noninteractive without exact current admission", () => {
  const pending = createAdmission().admission;
  pending.viewError(projectionDiagnostic, "revision-1", "active");
  expect(pending.isInteractive).toBe(false);

  const stale = admitted().admission;
  stale.viewError(projectionDiagnostic, "revision-2", "active", "s_stale2");
  expect(stale.isInteractive).toBe(true);
  stale.presentationBaseline("revision-2", "active");
  expect(stale.isInteractive).toBe(false);

  stale.receiverUnready();
  stale.receiverReady("revision-2", "current", "active");
  stale.viewReady("revision-2", "s_stale2", "active");
  expect(stale.isReady).toBe(true);
});

it("ignores a late error from the receiver's previous revision", () => {
  const { admission, effects } = admitted();
  admission.receiverReady("revision-2", "current", "active");
  effects.failView.mockClear();
  effects.viewFailed.mockClear();

  admission.viewError(projectionDiagnostic, "revision-1", "active", "s_123456");

  expect(effects.failView).not.toHaveBeenCalled();
  expect(effects.viewFailed).not.toHaveBeenCalled();
  admission.viewReady("revision-2", "s_next22", "active");
  expect(admission.isReady).toBe(true);
  expect(admission.identity).toEqual({ revision: "revision-2", sessionId: "s_next22" });
});

it("ignores a view error from another session at the current revision", () => {
  const { admission, effects } = admitted();
  effects.viewFailed.mockClear();

  admission.viewError(projectionDiagnostic, "revision-1", "active", "s_foreign");

  expect(admission.isReady).toBe(true);
  expect(admission.identity).toEqual({ revision: "revision-1", sessionId: "s_123456" });
  expect(effects.viewFailed).not.toHaveBeenCalled();
});

it("does not let a localized failure supersede a fatal view error", () => {
  const { admission, effects } = admitted();
  admission.viewError({ ...diagnostic, scope: "runtime" }, "revision-1", "active");
  expect(admission.isInteractive).toBe(false);
  effects.postMessage.mockClear();
  admission.presentationBaseline("revision-1", "active");
  expect(effects.postMessage).not.toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });
  admission.reactivate("active");
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });
  effects.observation.mockClear();

  admission.viewError(projectionDiagnostic, "revision-1", "active");
  admission.observation("error", [projectionDiagnostic], "revision-1", "s_123456");

  expect(admission.isInteractive).toBe(false);
  expect(effects.observation).not.toHaveBeenCalled();

  admission.receiverUnready();
  admission.receiverReady("revision-1", "current", "active");
  admission.viewReady("revision-1", "s_123456", "active");
  expect(admission.isReady).toBe(true);
  expect(admission.isInteractive).toBe(true);
});

it("does not let a localized view error supersede a fatal observation", () => {
  const { admission, effects } = admitted();
  effects.stopControls.mockClear();
  admission.observation(
    "error",
    [{ ...diagnostic, severity: "error", scope: "runtime" }],
    "revision-1",
    "s_123456",
  );
  expect(admission.isInteractive).toBe(false);
  expect(effects.clearObservations).toHaveBeenCalled();
  expect(effects.stopControls).toHaveBeenCalledOnce();
  effects.postMessage.mockClear();
  admission.presentationBaseline("revision-1", "active");
  admission.reactivate("active");
  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-change",
  });

  admission.viewError(projectionDiagnostic, "revision-1", "active");

  expect(admission.isInteractive).toBe(false);
});

it("settles a completed build without re-admitting its fatal view", () => {
  const { admission, effects } = admitted();
  effects.postMessage.mockClear();
  effects.ready.mockClear();
  admission.buildStarted("active");
  admission.viewError({ ...diagnostic, scope: "runtime" }, "revision-1", "active");

  admission.buildCompleted("revision-1", "active");

  expect(effects.postMessage).toHaveBeenCalledWith({
    type: "marimo-studio:presentation-refresh",
    phase: "settled",
  });
  expect(admission.isInteractive).toBe(false);
  expect(effects.ready).not.toHaveBeenCalled();

  admission.viewReady("revision-1", "s_123456", "active");
  expect(admission.isReady).toBe(true);
});

it("rejects observation evidence after build revokes admission", () => {
  const { admission, effects } = admitted();
  effects.observation.mockClear();
  admission.buildStarted("active");

  admission.observation("ready", [], "revision-1", "s_123456");

  expect(effects.observation).not.toHaveBeenCalled();
});

it("resets document ownership and records terminal failure explicitly", () => {
  const { admission, effects } = admitted();
  admission.resetDocument();
  expect(admission.snapshot).toMatchObject({
    admittedRevision: null,
    candidate: null,
    ready: null,
    receiver: { phase: "unready" },
    view: "waiting",
  });

  admission.viewSyncPending(diagnostic);
  admission.viewError(diagnostic, "revision-error", "active");
  expect(admission.snapshot).toMatchObject({ requirement: "ordinary", view: "failed" });
  expect(effects.viewFailed).toHaveBeenCalledWith(diagnostic, "revision-error");

  admission.dispose();
  expect(admission.snapshot.presentation.build).toBe("settled");
});
