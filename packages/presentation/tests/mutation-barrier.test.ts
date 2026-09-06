import type { PresentationRefreshBarrierResult } from "@marimo-studio/protocol/development-events";

import assert from "node:assert/strict";
import { expect, test, vi } from "vite-plus/test";

import { coordinatePresentationMutationBarrier } from "../src/document/mutation-barrier.ts";

const deferredResult = () => {
  let resolve = (_result: PresentationRefreshBarrierResult) => {};
  const promise = new Promise<PresentationRefreshBarrierResult>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

test("a parent rejection after readiness releases the mutation claims", async () => {
  const channel = new MessageChannel();
  const controller = new AbortController();
  const result = deferredResult();
  const onFailure = vi.fn();
  const ready = new Promise<unknown>((resolve) => {
    channel.port2.onmessage = (event) => resolve(event.data);
    channel.port2.start();
  });
  const barrier = coordinatePresentationMutationBarrier({
    drained: Promise.resolve(),
    generation: 4,
    onFailure,
    port: channel.port1,
    result: result.promise,
    signal: controller.signal,
  });

  assert.deepEqual(await ready, {
    schema: 1,
    type: "marimo-studio:editor-document-mutation-ready",
    generation: 4,
  });
  controller.abort(new DOMException("The parent timed out.", "AbortError"));
  result.resolve({
    schema: 1,
    type: "marimo-studio:presentation-refresh-barrier-failed",
    generation: 4,
  });
  await barrier;
  assert.equal(onFailure.mock.calls.length, 1);
  channel.port1.close();
  channel.port2.close();
});

test("an accepted barrier retains claims for the normal refresh settlement", async () => {
  const result = deferredResult();
  const onFailure = vi.fn();
  const port = { close: vi.fn(), postMessage: vi.fn() };
  const barrier = coordinatePresentationMutationBarrier({
    drained: Promise.resolve(),
    generation: 5,
    onFailure,
    port,
    result: result.promise,
    signal: new AbortController().signal,
  });
  await vi.waitFor(() => expect(port.postMessage).toHaveBeenCalledOnce());
  result.resolve({
    schema: 1,
    type: "marimo-studio:presentation-refresh-barrier-accepted",
    generation: 5,
  });

  await barrier;
  expect(onFailure).not.toHaveBeenCalled();
  expect(port.close).not.toHaveBeenCalled();
});

test("a superseded drain fails without announcing mutation readiness", async () => {
  const onFailure = vi.fn();
  const port = { close: vi.fn(), postMessage: vi.fn() };

  await coordinatePresentationMutationBarrier({
    drained: Promise.reject(
      new DOMException("The presentation changed before the mutation paused.", "AbortError"),
    ),
    generation: 6,
    onFailure,
    port,
    result: deferredResult().promise,
    signal: new AbortController().signal,
  });

  expect(port.postMessage).not.toHaveBeenCalled();
  expect(onFailure).toHaveBeenCalledOnce();
  expect(port.close).toHaveBeenCalledOnce();
});
