// @vitest-environment jsdom

import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  classifyProjectedOutputFunctionRequest,
  PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE,
  PROJECTED_OUTPUT_FUNCTION_DRAIN_TIMEOUT_MS,
  PROJECTED_OUTPUT_OWNER_ATTRIBUTE,
  PROJECTED_OUTPUT_SCOPE_ATTRIBUTE,
  ProjectedOutputFunctionGate,
} from "../src/projected-output-function-gate.ts";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

const projectedElement = (activeOwner: string, outputOwner: string) => {
  const wrapper = document.createElement("div");
  wrapper.setAttribute(PROJECTED_OUTPUT_SCOPE_ATTRIBUTE, "");
  wrapper.setAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, activeOwner);
  wrapper.setAttribute(PROJECTED_OUTPUT_OWNER_ATTRIBUTE, outputOwner);
  const element = document.createElement("marimo-table");
  wrapper.append(element);
  document.body.append(wrapper);
  return { element, wrapper };
};

test("current projected and native function requests start in the calling turn", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element } = projectedElement("revision-a", "revision-a");
  const native = document.createElement("marimo-table");
  document.body.append(native);
  const projectedSend = vi.fn(async () => "projected");
  const nativeSend = vi.fn(async () => "native");

  const projected = gate.run(element, projectedSend);
  expect(projectedSend).toHaveBeenCalledOnce();
  await expect(projected).resolves.toBe("projected");

  const transition = gate.beginTransition();
  const nativeRequest = gate.run(native, nativeSend);
  expect(nativeSend).toHaveBeenCalledOnce();
  await expect(nativeRequest).resolves.toBe("native");
  gate.completeTransition(transition);
  client.dispose();
  gate.dispose();
});

test("current projected and native failures retain their request error", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element } = projectedElement("revision-a", "revision-a");
  const native = document.createElement("marimo-table");
  document.body.append(native);
  const projectedFailure = new Error("projected failure");
  const nativeFailure = new Error("native failure");

  await expect(
    gate.run(element, () =>
      classifyProjectedOutputFunctionRequest(Promise.reject(projectedFailure)),
    ),
  ).rejects.toBe(projectedFailure);
  const transition = gate.beginTransition();
  await expect(
    gate.run(native, () => classifyProjectedOutputFunctionRequest(Promise.reject(nativeFailure))),
  ).rejects.toBe(nativeFailure);

  gate.completeTransition(transition);
  client.dispose();
  gate.dispose();
});

test("a paused request resumes on rollback and stops at a replacement revision", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedElement("revision-a", "revision-a");
  const rollbackClaim = gate.beginTransition();
  const rollbackSend = vi.fn(async () => "rollback");
  const rollback = gate.run(element, rollbackSend);
  expect(rollbackSend).not.toHaveBeenCalled();

  gate.completeTransition(rollbackClaim);
  await expect(rollback).resolves.toBe("rollback");
  expect(rollbackSend).toHaveBeenCalledOnce();

  const replacementClaim = gate.beginTransition();
  const replacementSend = vi.fn(async () => "replacement");
  const replacement = gate.run(element, replacementSend);
  const rejected = expect(replacement).rejects.toMatchObject({ name: "AbortError" });
  wrapper.setAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, "revision-b");
  wrapper.setAttribute(PROJECTED_OUTPUT_OWNER_ATTRIBUTE, "revision-b");
  gate.completeTransition(replacementClaim);

  await rejected;
  expect(replacementSend).not.toHaveBeenCalled();
  client.dispose();
  gate.dispose();
});

test("a transition drains admitted function requests before document mutation", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element } = projectedElement("revision-a", "revision-a");
  let resolveAdmission = (_result: string) => {};
  const admission = new Promise<string>((resolve) => {
    resolveAdmission = resolve;
  });
  const request = gate.run(element, () => classifyProjectedOutputFunctionRequest(admission));
  const transition = gate.beginTransition();
  let drained = false;
  void transition.drained.then(() => {
    drained = true;
  });
  await Promise.resolve();
  expect(drained).toBe(false);

  resolveAdmission("admitted");
  await transition.drained;
  expect(drained).toBe(true);
  gate.completeTransition(transition);
  await expect(request).resolves.toBe("admitted");
  client.dispose();
  gate.dispose();
});

test("a transition rejects a stalled admission at its owned deadline", async () => {
  vi.useFakeTimers();
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element } = projectedElement("revision-a", "revision-a");
  const admission = new Promise<string>(() => {});
  const request = gate.run(element, () => classifyProjectedOutputFunctionRequest(admission));
  const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
  const transition = gate.beginTransition();
  const timedOut = expect(transition.drained).rejects.toMatchObject({
    name: "ProjectedOutputFunctionDrainTimeoutError",
  });

  await vi.advanceTimersByTimeAsync(PROJECTED_OUTPUT_FUNCTION_DRAIN_TIMEOUT_MS);
  await timedOut;

  gate.cancelTransition(transition);
  client.dispose();
  gate.dispose();
  await rejected;
});

test("a resumed request rejects an owner change before sending", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedElement("revision-a", "revision-a");
  const claim = gate.beginTransition();
  const send = vi.fn(async () => "sent");
  const request = gate.run(element, send);

  gate.completeTransition(claim);
  wrapper.setAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, "revision-b");
  await expect(request).rejects.toMatchObject({ name: "AbortError" });
  expect(send).not.toHaveBeenCalled();
  client.dispose();
  gate.dispose();
});

test("an active request failure survives rollback and stops at replacement", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedElement("revision-a", "revision-a");
  let rejectRollback = (_cause: Error) => {};
  const rollbackSend = new Promise<string>((_resolve, reject) => {
    rejectRollback = reject;
  });
  const rollback = gate.run(element, () => classifyProjectedOutputFunctionRequest(rollbackSend));
  let rollbackSettled = false;
  void rollback.catch(() => {
    rollbackSettled = true;
  });
  const rollbackFailure = new Error("retained failure");
  const rollbackClaim = gate.beginTransition();
  rejectRollback(rollbackFailure);
  await Promise.resolve();
  expect(rollbackSettled).toBe(false);

  gate.completeTransition(rollbackClaim);
  await expect(rollback).rejects.toBe(rollbackFailure);

  let rejectReplacement = (_cause: Error) => {};
  const replacementSend = new Promise<string>((_resolve, reject) => {
    rejectReplacement = reject;
  });
  const replacement = gate.run(element, () =>
    classifyProjectedOutputFunctionRequest(replacementSend),
  );
  const replacementClaim = gate.beginTransition();
  rejectReplacement(new Error("replaced failure"));
  wrapper.setAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, "revision-b");
  wrapper.setAttribute(PROJECTED_OUTPUT_OWNER_ATTRIBUTE, "revision-b");
  gate.completeTransition(replacementClaim);
  await expect(replacement).rejects.toMatchObject({ name: "AbortError" });
  client.dispose();
  gate.dispose();
});

test("a stale rendered generation cannot dispatch outside a transition", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element } = projectedElement("cell-version-b", "cell-version-a");
  const send = vi.fn(async () => "stale");

  await expect(gate.run(element, send)).rejects.toMatchObject({ name: "AbortError" });
  expect(send).not.toHaveBeenCalled();
  client.dispose();
  gate.dispose();
});

test("an active request result waits for rollback and stops at replacement", async () => {
  const gate = new ProjectedOutputFunctionGate();
  const client = gate.activateClient();
  const { element, wrapper } = projectedElement("revision-a", "revision-a");
  let resolveRollback = (_result: string) => {};
  const rollbackSend = new Promise<string>((resolve) => {
    resolveRollback = resolve;
  });
  const rollback = gate.run(element, () => classifyProjectedOutputFunctionRequest(rollbackSend));
  let rollbackSettled = false;
  void rollback.then(() => {
    rollbackSettled = true;
  });
  const rollbackClaim = gate.beginTransition();
  resolveRollback("rollback");
  await Promise.resolve();
  expect(rollbackSettled).toBe(false);

  gate.completeTransition(rollbackClaim);
  await expect(rollback).resolves.toBe("rollback");

  let resolveReplacement = (_result: string) => {};
  const replacementSend = new Promise<string>((resolve) => {
    resolveReplacement = resolve;
  });
  const replacement = gate.run(element, () =>
    classifyProjectedOutputFunctionRequest(replacementSend),
  );
  const rejected = expect(replacement).rejects.toMatchObject({ name: "AbortError" });
  const replacementClaim = gate.beginTransition();
  resolveReplacement("replacement");
  wrapper.setAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, "revision-b");
  wrapper.setAttribute(PROJECTED_OUTPUT_OWNER_ATTRIBUTE, "revision-b");
  gate.completeTransition(replacementClaim);

  await rejected;
  client.dispose();
  gate.dispose();
});

test("wrapper and transport disposal cancel pending projected requests", async () => {
  const gate = new ProjectedOutputFunctionGate();
  let client = gate.activateClient();
  const { element, wrapper } = projectedElement("revision-b", "revision-a");
  const retired = gate.run(element, async () => "retired");
  const retiredRejection = expect(retired).rejects.toMatchObject({ name: "AbortError" });
  wrapper.remove();
  await retiredRejection;

  client.dispose();
  client = gate.activateClient();
  const current = projectedElement("revision-a", "revision-a");
  const held = new Promise<string>(() => {});
  const send = vi.fn(() => held);
  const active = gate.run(current.element, send);
  const activeRejection = expect(active).rejects.toMatchObject({ name: "AbortError" });
  expect(send).toHaveBeenCalledOnce();
  client.dispose();
  await activeRejection;
  gate.dispose();
});
