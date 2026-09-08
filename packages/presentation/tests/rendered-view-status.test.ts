import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  setRuntimeConnectionState,
  startRenderedViewObserver,
  stopRenderedViewObserver,
} from "../src/rendered-view-observer.ts";
import { renderedViewIdentity } from "../src/rendered-view-state.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  runtimeSessionId: "s_abc123",
};

afterEach(() => {
  stopRenderedViewObserver();
  document.body.replaceChildren();
  globalThis.history.replaceState({}, "", "/");
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = undefined;
  vi.restoreAllMocks();
});

test("pre-config evidence uses the server-minted mount runtime", () => {
  globalThis.history.replaceState({}, "", "/dashboard/?runtime=wasm");
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = "s_forged";

  expect(renderedViewIdentity()).toMatchObject({
    runtime: "server",
    sessionId: "s_abc123",
  });
});

test("a direct wrapper shows its runtime waiting status", () => {
  commitRuntimeConfig(runtimeConfig());
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = "s_forged";
  expect(renderedViewIdentity().sessionId).toBe("s_abc123");
  vi.spyOn(globalThis.parent, "postMessage").mockImplementation(() => undefined);
  globalThis.history.replaceState({}, "", "/dashboard/");
  startRenderedViewObserver(async () => {});

  setRuntimeConnectionState("connecting", {
    code: "runtime-startup-pending",
    message: "The runtime is starting.",
    hint: "Wait for the notebook session.",
  });

  const host = document.querySelector<HTMLElement>("[data-marimo-studio-runtime-diagnostic]")!;
  expect(host.hidden).toBe(false);
  expect(host.getAttribute("role")).toBe("status");
  expect(host.textContent).toBe("The runtime is starting.");
});

test("runtime errors publish the rendered session identity", () => {
  commitRuntimeConfig(runtimeConfig());
  const postMessage = vi
    .spyOn(globalThis.parent, "postMessage")
    .mockImplementation(() => undefined);
  startRenderedViewObserver(async () => {});
  postMessage.mockClear();

  setRuntimeConnectionState("error", {
    code: "runtime-failed",
    message: "The runtime stopped.",
    hint: "Restart the notebook session.",
  });

  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:view-error",
      revision: "presentation-revision",
      sessionId: "s_abc123",
    }),
    globalThis.location.origin,
  );
});

test("publishes a startup error before rendered-view observers are attached", () => {
  const postMessage = vi
    .spyOn(globalThis.parent, "postMessage")
    .mockImplementation(() => undefined);
  setRuntimeConnectionState("error", {
    code: "publication-error",
    message: "Notebook states could not be captured.",
    hint: "Check the notebook outputs.",
  });
  expect(postMessage).toHaveBeenCalledTimes(1);
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "marimo-studio:view-error",
      diagnostic: expect.objectContaining({ code: "publication-error", scope: "runtime" }),
    }),
    globalThis.location.origin,
  );
  const alert = document.querySelector('[role="alert"]');
  expect(alert?.textContent).toBe("Notebook states could not be captured.");
});
