import type { FrameBridgeMessage } from "@marimo-studio/protocol/frame-bridge";

import { parseFrameBridgeMessage } from "@marimo-studio/protocol/frame-bridge";
import { expect, test, vi } from "vite-plus/test";

import {
  applyFrameQuery,
  connectFrameControlBridge,
  releaseFrameBridge,
  resizeFrame,
} from "../src/features/preview/frame-bridge.ts";

const identity = {
  lifecycleId: 7,
  revision: "revision-a",
  runtime: "wasm",
  sessionId: "s_preview",
  view: "dashboard",
};

const dispatch = (source: Window, data: FrameBridgeMessage) => {
  const event = new MessageEvent("message", { data, origin: "null" });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

test("frame bridge binds controls and query replies to the active document", async () => {
  const frame = document.createElement("iframe");
  frame.dataset.previewFrame = "";
  frame.dataset.previewLifecycleId = String(identity.lifecycleId);
  document.body.append(frame);
  const source = frame.contentWindow!;
  const post = vi.spyOn(source, "postMessage");

  dispatch(source, {
    type: "marimo-studio:frame-bridge-ready",
    generation: "generation-a",
    controls: [{ objectId: "wasm-cell-control", value: 1 }],
    ...identity,
  });
  const controls = connectFrameControlBridge(frame, {
    revision: identity.revision,
    runtime: identity.runtime,
    sessionId: identity.sessionId,
  });
  expect(controls?.snapshot()).toEqual([{ objectId: "wasm-cell-control", value: 1 }]);
  const updates = vi.fn();
  const stopUpdates = controls?.subscribe(updates);

  resizeFrame(frame);
  expect(post.mock.calls.at(-1)?.[0]).toMatchObject({
    type: "marimo-studio:frame-resize",
    ...identity,
  });

  const query = applyFrameQuery(frame, "?region=emea", "#detail");
  const request = parseFrameBridgeMessage(post.mock.calls.at(-1)?.[0]);
  expect(request).toMatchObject({
    type: "marimo-studio:frame-query-apply",
    query: "?region=emea",
    hash: "#detail",
    ...identity,
  });
  if (request?.type !== "marimo-studio:frame-query-apply") {
    throw new Error("The frame bridge did not publish its query request");
  }
  dispatch(source, {
    type: "marimo-studio:frame-bridge-ready",
    generation: "generation-a",
    controls: [{ objectId: "wasm-cell-control", value: 1 }],
    ...identity,
  });
  dispatch(source, {
    type: "marimo-studio:frame-query-applied",
    generation: "generation-a",
    requestId: request.requestId,
    ...identity,
  });
  await expect(query).resolves.toBeUndefined();
  dispatch(source, {
    type: "marimo-studio:frame-control-update",
    generation: "generation-a",
    update: { objectId: "wasm-cell-control", value: 2 },
    ...identity,
  });
  expect(updates).toHaveBeenCalledWith({ objectId: "wasm-cell-control", value: 2 });

  const pendingControl = controls!.apply([{ objectId: "wasm-cell-control", value: 2 }]);
  const pendingQuery = applyFrameQuery(frame, "?region=apac");
  releaseFrameBridge(frame);
  await expect(pendingControl).rejects.toThrow("frame was released");
  await expect(pendingQuery).rejects.toThrow("frame was released");

  frame.dataset.previewLifecycleId = "8";
  dispatch(source, {
    type: "marimo-studio:frame-bridge-ready",
    generation: "generation-stale",
    controls: [],
    ...identity,
  });
  expect(
    connectFrameControlBridge(frame, {
      revision: identity.revision,
      runtime: identity.runtime,
      sessionId: identity.sessionId,
    }),
  ).toBeUndefined();
  controls?.dispose();
  stopUpdates?.();
  frame.remove();
});
