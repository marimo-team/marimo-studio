import type { ObserveViewRequest } from "@marimo-studio/protocol/development-events";
import type { ViewObservationMessage } from "@marimo-studio/protocol/preview-messages";

import {
  browserObservationSchema,
  type RuntimeStatusPhase,
  type RuntimeStatusReport,
} from "@marimo-studio/protocol/browser-observations";
import { expect, it, vi } from "vite-plus/test";

import type { RenderedBrowserObservation } from "../src/features/preview/observation-remote.ts";

import { PreviewObservationController } from "../src/features/preview/observation-controller.ts";
import { emptyProjectionEvidence } from "./fixtures.ts";

const request: ObserveViewRequest = {
  schema: 1,
  requestId: "request-dashboard",
  view: "dashboard",
  runtime: "server",
  runtimeInstance: "runtime-instance",
  revision: "revision-dashboard",
};

const observation = (state: "loading" | "ready"): ViewObservationMessage => ({
  type: "marimo-studio:view-observation",
  requestId: request.requestId,
  view: request.view,
  runtime: request.runtime,
  lifecycleId: 1,
  runtimeInstance: request.runtimeInstance,
  revision: request.revision,
  state,
  diagnostics: [],
  sessionId: "s_123456",
  query: "region=emea",
  ...emptyProjectionEvidence,
});

const acceptObservation = (message: ViewObservationMessage): RuntimeStatusReport => {
  let phase: RuntimeStatusPhase = "ready";
  if (message.state === "loading") {
    phase = "synchronizing";
  } else if (message.state === "error") {
    phase = "failed";
  }
  const retained = message.diagnostics.slice(0, 20);
  return {
    runtime: message.runtime,
    view: message.view,
    revision: message.revision,
    sessionId: message.sessionId,
    current: { phase, diagnostics: message.diagnostics },
    transitions: [
      {
        sequence: 0,
        observedAt: 1_000,
        revision: message.revision,
        sessionId: message.sessionId,
        phase,
        diagnostics: retained,
        diagnosticsTruncated: retained.length < message.diagnostics.length,
      },
    ],
  };
};

const previewHost = () => {
  const preview = document.createElement("iframe");
  const postMessage = vi.fn();
  Object.defineProperty(preview, "contentWindow", {
    configurable: true,
    value: { postMessage },
  });
  return { preview, postMessage };
};

it("keeps an observation request until terminal evidence is recorded", async () => {
  const { preview, postMessage } = previewHost();
  const record = vi.fn(async (_value: RenderedBrowserObservation) => undefined);
  const controller = new PreviewObservationController("server", preview, acceptObservation, record);

  controller.request(request, 1);
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:observe-view",
      lifecycleId: 1,
      requestId: request.requestId,
    }),
    "*",
  );
  controller.receive(observation("loading"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(1));
  expect(record).toHaveBeenLastCalledWith(
    expect.objectContaining({ runtimeStatus: acceptObservation(observation("loading")) }),
  );
  controller.post();
  expect(postMessage).toHaveBeenCalledTimes(2);

  controller.receive(observation("ready"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(2));
  controller.post();
  expect(postMessage).toHaveBeenCalledTimes(2);
  const uploads = record.mock.calls.map(([payload], sequence) =>
    browserObservationSchema.parse({
      ...payload,
      schema: 1,
      clientId: "browser-client-1234",
      sequence,
    }),
  );
  expect(uploads.map(({ runtimeStatus }) => runtimeStatus.current.phase)).toEqual([
    "synchronizing",
    "ready",
  ]);
});

it("releases terminal evidence after its bounded upload fails", async () => {
  const { preview, postMessage } = previewHost();
  const record = vi.fn(async (_value: RenderedBrowserObservation) => {
    throw new Error("network unavailable");
  });
  const controller = new PreviewObservationController("server", preview, acceptObservation, record);
  const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

  controller.request(request, 1);
  controller.receive(observation("ready"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(1));
  await vi.waitFor(() => expect(warning).toHaveBeenCalledTimes(1));
  controller.post();

  expect(postMessage).toHaveBeenCalledTimes(1);
});

it("does not resend a request while terminal evidence is uploading", async () => {
  const { preview, postMessage } = previewHost();
  let finishUpload!: () => void;
  const record = vi.fn(
    async (_value: RenderedBrowserObservation) =>
      await new Promise<void>((resolve) => {
        finishUpload = resolve;
      }),
  );
  const controller = new PreviewObservationController("server", preview, acceptObservation, record);

  controller.request(request, 1);
  controller.receive(observation("ready"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(1));
  controller.post();
  controller.receive(observation("ready"));

  expect(postMessage).toHaveBeenCalledTimes(1);
  expect(record).toHaveBeenCalledTimes(1);
  finishUpload();
  await vi.waitFor(() => {
    controller.post();
    expect(postMessage).toHaveBeenCalledTimes(1);
  });
});

it("a new observation request supersedes stale browser work", () => {
  const { preview, postMessage } = previewHost();
  const controller = new PreviewObservationController("server", preview, acceptObservation);

  controller.request({ ...request, requestId: "stale-request", revision: "revision-1" }, 1);
  controller.request({ ...request, requestId: "current-request", revision: "revision-2" }, 2);
  postMessage.mockClear();
  controller.post();

  expect(postMessage).toHaveBeenCalledTimes(1);
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ requestId: "current-request", revision: "revision-2" }),
    "*",
  );
});

it("drops superseded replies before accepting their runtime state", () => {
  const { preview } = previewHost();
  const accept = vi.fn(acceptObservation);
  const controller = new PreviewObservationController("server", preview, accept);

  controller.request({ ...request, requestId: "stale-request", revision: "revision-1" }, 1);
  controller.request({ ...request, requestId: "current-request", revision: "revision-2" }, 2);
  controller.receive({
    ...observation("ready"),
    requestId: "stale-request",
    revision: "revision-1",
  });

  expect(accept).not.toHaveBeenCalled();

  const current = {
    ...observation("ready"),
    lifecycleId: 2,
    requestId: "current-request",
    revision: "revision-2",
  };
  controller.receive({ ...current, lifecycleId: 1 });
  expect(accept).not.toHaveBeenCalled();
  controller.receive(current);

  expect(accept).toHaveBeenCalledTimes(1);
  expect(accept).toHaveBeenCalledWith(current);
});
