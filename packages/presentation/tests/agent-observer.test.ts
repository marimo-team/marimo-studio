import assert from "node:assert/strict";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { startPresentationObservers, stopPresentationObservers } from "../src/observers.ts";
import { setRuntimeConnectionState } from "../src/rendered-view-observer.ts";
import { initializeViewStyles, ViewStyleController } from "../src/view-styles/runtime.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
};

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

afterEach(stopPresentationObservers);

test("browser evidence stays loading until stale projections settle", async () => {
  document.body.innerHTML = `<span mo-value="report" data-state="stale"></span>`;
  const source = document.querySelector<HTMLElement>("[mo-value]")!;
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      source: globalThis.parent,
      data: {
        type: "marimo-studio:observe-view",
        runtime: "server",
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "runtime-instance",
        requestId: "request-stale",
      },
    }),
  );
  await settleMutations();
  source.dataset.state = "ready";
  await settleMutations();

  const states = postMessage.mock.calls.flatMap(([message]) =>
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    message.type === "marimo-studio:view-observation" &&
    "requestId" in message &&
    message.requestId === "request-stale" &&
    "state" in message
      ? [message.state]
      : [],
  );
  expect(states).toEqual(["loading", "ready"]);
  postMessage.mockRestore();
});

test("a settled page publishes actionable browser evidence", async () => {
  document.body.innerHTML = `
    <span
      mo-value="summary.total"
      data-state="error"
      data-marimo-diagnostic-code="missing-variable"
      data-marimo-diagnostic-message="summary is unavailable."
      data-marimo-diagnostic-hint="Restore summary in the notebook."
    ></span>
  `;
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  assert.equal(
    postMessage.mock.calls.some(
      ([message]) =>
        typeof message === "object" &&
        message !== null &&
        "type" in message &&
        message.type === "marimo-studio:view-observation",
    ),
    false,
  );
  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      source: globalThis.parent,
      data: {
        type: "marimo-studio:observe-view",
        runtime: "server",
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "runtime-instance",
        requestId: "request-dashboard",
      },
    }),
  );
  await settleMutations();

  const observation = postMessage.mock.calls
    .map(([message]) => message)
    .find(
      (message) =>
        typeof message === "object" &&
        message !== null &&
        "type" in message &&
        message.type === "marimo-studio:view-observation",
    );

  assert.deepEqual(observation, {
    type: "marimo-studio:view-observation",
    runtime: "server",
    view: "dashboard",
    revision: "presentation-revision",
    state: "error",
    diagnostics: [
      {
        scope: "host",
        code: "missing-variable",
        severity: "error",
        message: "summary is unavailable.",
        hint: "Restore summary in the notebook.",
        view: "dashboard",
        target: "summary.total",
      },
    ],
    runtimeInstance: "runtime-instance",
    sessionId: null,
    requestId: "request-dashboard",
    query: "",
  });
});

test("a view-style startup failure is reported as presentation evidence", async () => {
  document.body.innerHTML = '<main id="app-shell"></main>';
  await initializeViewStyles(false);
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      source: globalThis.parent,
      data: {
        type: "marimo-studio:observe-view",
        runtime: "server",
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "runtime-instance",
        requestId: "request-styles",
      },
    }),
  );
  await settleMutations();

  const observation = postMessage.mock.calls
    .map(([message]) => message)
    .find(
      (message) =>
        typeof message === "object" &&
        message !== null &&
        "type" in message &&
        message.type === "marimo-studio:view-observation" &&
        "requestId" in message &&
        message.requestId === "request-styles",
    );
  expect(observation).toMatchObject({
    state: "error",
    diagnostics: [
      {
        scope: "presentation",
        code: "view-styles-unsupported",
        severity: "error",
        view: "dashboard",
      },
    ],
  });
});

test("browser evidence waits for live utility regeneration", async () => {
  document.body.innerHTML = '<main id="app-shell" class="grid"></main>';
  let rejectGeneration!: (error: Error) => void;
  const generation = new Promise<string>((_resolve, reject) => {
    rejectGeneration = reject;
  });
  let calls = 0;
  const styles = new ViewStyleController(async () => {
    calls += 1;
    return calls === 1 ? "/* grid */" : generation;
  });
  await styles.refresh();
  styles.observe();
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");

  document.querySelector("#app-shell")!.classList.add("p-4");
  await settleMutations();
  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      source: globalThis.parent,
      data: {
        type: "marimo-studio:observe-view",
        runtime: "server",
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "runtime-instance",
        requestId: "request-live-styles",
      },
    }),
  );
  await settleMutations();
  rejectGeneration(new Error("generator failed"));
  await settleMutations();

  const states = postMessage.mock.calls.flatMap(([message]) =>
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    message.type === "marimo-studio:view-observation" &&
    "requestId" in message &&
    message.requestId === "request-live-styles" &&
    "state" in message
      ? [message.state]
      : [],
  );
  expect(states).toEqual(["loading", "error"]);
  styles.disconnect();
});
