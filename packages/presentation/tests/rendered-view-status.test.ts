import "./framed-document.ts";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { beginPresentationRefresh, setPresentationRefreshState } from "../src/readiness.ts";
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
  for (const name of document.documentElement.getAttributeNames()) {
    if (name.startsWith("data-marimo-studio-")) document.documentElement.removeAttribute(name);
  }
  globalThis.history.replaceState({}, "", "/");
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = undefined;
  vi.restoreAllMocks();
});

test("pre-config evidence uses the server-minted mount runtime", () => {
  expect(document.documentElement.hasAttribute("data-marimo-studio-revision")).toBe(false);
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
  expect(document.documentElement.dataset.marimoStudioState).toBe("error");
});

test("a failed build stays visible across a successful document refresh until its own recovery", () => {
  commitRuntimeConfig(runtimeConfig());
  startRenderedViewObserver(async () => {});
  setRuntimeConnectionState("ready");
  const build = beginPresentationRefresh("build");
  expect(document.documentElement.dataset.marimoStudioState).toBe("loading");
  setPresentationRefreshState(build, "error", {
    scope: "presentation",
    severity: "error",
    code: "view-build-failed",
    message: "Latest build failed. Showing the previous build.",
    hint: "Fix the source.",
    view: "dashboard",
  });
  const refresh = beginPresentationRefresh("document");
  setPresentationRefreshState(refresh, "ready");
  expect(document.documentElement.dataset.marimoStudioState).toBe("error");
  expect(document.querySelector("[data-marimo-studio-diagnostic]")?.textContent).toContain(
    "Latest build failed",
  );
  expect(document.documentElement.dataset.marimoStudioRevision).toBe("presentation-revision");
  const retry = beginPresentationRefresh("build");
  setPresentationRefreshState(retry, "ready");
  expect(document.documentElement.dataset.marimoStudioState).toBe("ready");
  expect(document.querySelector<HTMLElement>("[data-marimo-studio-diagnostic]")?.hidden).toBe(true);
});

test("disconnected updates remain visibly pending until recovery while build errors take precedence", () => {
  commitRuntimeConfig(runtimeConfig());
  startRenderedViewObserver(async () => {});
  setRuntimeConnectionState("ready");
  const documentRefresh = beginPresentationRefresh("document");
  const connection = beginPresentationRefresh("development");
  setPresentationRefreshState(connection, "loading", {
    scope: "presentation",
    severity: "warning",
    code: "development-disconnected",
    message: "Live updates disconnected. Reconnecting…",
    hint: "Check that the Studio server is available.",
    view: "dashboard",
  });
  const host = document.querySelector<HTMLElement>("[data-marimo-studio-diagnostic]")!;
  expect(document.documentElement.dataset.marimoStudioState).toBe("loading");
  expect(host.hidden).toBe(false);
  expect(host.getAttribute("role")).toBe("status");
  expect(host.textContent).toBe("Live updates disconnected. Reconnecting…");
  const build = beginPresentationRefresh("build");
  setPresentationRefreshState(build, "error", {
    scope: "presentation",
    severity: "error",
    code: "view-build-failed",
    message: "Latest build failed. Showing the previous build.",
    hint: "Fix the source.",
    view: "dashboard",
  });
  expect(document.documentElement.dataset.marimoStudioState).toBe("error");
  expect(host.getAttribute("role")).toBe("alert");
  expect(host.textContent).toContain("Latest build failed");
  setPresentationRefreshState(build, "ready");
  expect(host.textContent).toBe("Live updates disconnected. Reconnecting…");
  setPresentationRefreshState(documentRefresh, "ready");
  setPresentationRefreshState(connection, "ready");
  expect(document.documentElement.dataset.marimoStudioState).toBe("ready");
  expect(host.hidden).toBe(true);
});
