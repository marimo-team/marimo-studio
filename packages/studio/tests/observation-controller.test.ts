import type { ObserveViewRequest } from "@marimo-studio/protocol/development-events";
import type { ViewObservationMessage } from "@marimo-studio/protocol/preview-messages";

import { expect, it, vi } from "vite-plus/test";

import { PreviewObservationController } from "../src/features/preview/observation-controller.ts";

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
  runtimeInstance: request.runtimeInstance,
  revision: request.revision,
  state,
  diagnostics: [],
  sessionId: "s_123456",
  query: "region=emea",
});

const runtimeStatus = () => ({
  runtime: "server",
  view: "dashboard",
  revision: "revision-dashboard",
  sessionId: "s_123456",
  current: { phase: "ready" as const, diagnostics: [] },
  transitions: [
    {
      sequence: 0,
      observedAt: 1_000,
      revision: "revision-dashboard",
      sessionId: "s_123456",
      phase: "ready" as const,
      diagnostics: [],
      diagnosticsTruncated: false,
    },
  ],
});

it("keeps an observation request until terminal evidence is recorded", async () => {
  document.body.innerHTML = "<iframe></iframe>";
  const preview = document.querySelector("iframe")!;
  const postMessage = vi.spyOn(preview.contentWindow!, "postMessage");
  const record = vi.fn(async () => undefined);
  const controller = new PreviewObservationController("server", preview, runtimeStatus, record);

  controller.request(request);
  controller.receive(observation("loading"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(1));
  expect(record).toHaveBeenLastCalledWith(
    expect.objectContaining({ runtimeStatus: runtimeStatus() }),
  );
  controller.post();
  expect(postMessage).toHaveBeenCalledTimes(2);

  controller.receive(observation("ready"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(2));
  controller.post();
  expect(postMessage).toHaveBeenCalledTimes(2);
});

it("releases terminal evidence after its bounded upload fails", async () => {
  document.body.innerHTML = "<iframe></iframe>";
  const preview = document.querySelector("iframe")!;
  const postMessage = vi.spyOn(preview.contentWindow!, "postMessage");
  const record = vi.fn(async () => {
    throw new Error("network unavailable");
  });
  const controller = new PreviewObservationController("server", preview, runtimeStatus, record);
  const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);

  controller.request(request);
  controller.receive(observation("ready"));
  await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(1));
  await vi.waitFor(() => expect(warning).toHaveBeenCalledTimes(1));
  controller.post();

  expect(postMessage).toHaveBeenCalledTimes(1);
});

it("does not resend a request while terminal evidence is uploading", async () => {
  document.body.innerHTML = "<iframe></iframe>";
  const preview = document.querySelector("iframe")!;
  const postMessage = vi.spyOn(preview.contentWindow!, "postMessage");
  let finishUpload!: () => void;
  const record = vi.fn(
    async () =>
      await new Promise<void>((resolve) => {
        finishUpload = resolve;
      }),
  );
  const controller = new PreviewObservationController("server", preview, runtimeStatus, record);

  controller.request(request);
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
  document.body.innerHTML = "<iframe></iframe>";
  const preview = document.querySelector("iframe")!;
  const postMessage = vi.spyOn(preview.contentWindow!, "postMessage");
  const controller = new PreviewObservationController("server", preview, runtimeStatus);

  controller.request({ ...request, requestId: "stale-request", revision: "revision-1" });
  controller.request({ ...request, requestId: "current-request", revision: "revision-2" });
  postMessage.mockClear();
  controller.post();

  expect(postMessage).toHaveBeenCalledTimes(1);
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ requestId: "current-request", revision: "revision-2" }),
    globalThis.location.origin,
  );
});
