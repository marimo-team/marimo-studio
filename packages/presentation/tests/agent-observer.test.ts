import { previewMessageSchema } from "@marimo-studio/protocol/preview-messages";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import assert from "node:assert/strict";
import { afterEach, beforeEach, expect, test, vi } from "vite-plus/test";

import { startPresentationObservers, stopPresentationObservers } from "../src/observers.ts";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import { setRuntimeConnectionState } from "../src/rendered-view-observer.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { markValueError } from "../src/values/hosts.ts";
import { initializeViewStyles, ViewStyleController } from "../src/view-styles/runtime.ts";
import { projectionRequest, projectionRuntimeConfig, runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  runtimeSessionId: "s_abc123",
};

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

afterEach(() => {
  stopPresentationObservers();
  projectionHosts.disconnect();
  document.body.replaceChildren();
});

beforeEach(() => commitRuntimeConfig(runtimeConfig()));

test("browser evidence stays loading until stale projections settle", async () => {
  commitRuntimeConfig(projectionRuntimeConfig([projectionRequest("report", "value")]));
  document.body.innerHTML = `<span mo-value="report" data-marimo-studio-site="site:value:report" data-state="stale"></span>`;
  const source = document.querySelector<HTMLElement>("[mo-value]")!;
  projectionHosts.connect();
  source.dataset.state = "stale";
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
        lifecycleId: 1,
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "server-instance",
        requestId: "request-stale",
      },
    }),
  );
  await settleMutations();
  source.dataset.state = "ready";
  await settleMutations();

  const states = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const observation = previewMessageSchema.parse(payload.data);
    return observation?.type === "marimo-studio:view-observation" &&
      observation.requestId === "request-stale"
      ? [observation.state]
      : [];
  });
  expect(states).toEqual(["loading", "ready"]);
  postMessage.mockRestore();
});

test("a settled page publishes actionable browser evidence", async () => {
  const config = commitRuntimeConfig(
    projectionRuntimeConfig([projectionRequest("summary.total", "value")]),
  );
  document.body.innerHTML = `
    <span
      mo-value="summary.total"
      data-marimo-studio-site="site:value:summary.total"
    ></span>
  `;
  projectionHosts.connect();
  markValueError(
    "summary.total",
    {
      code: "missing-variable",
      message: "summary is unavailable.",
      hint: "Restore summary in the notebook.",
    },
    config.projectionRevision,
  );
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  const terminal = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const parsed = previewMessageSchema.parse(payload.data);
    return parsed?.type === "marimo-studio:view-error" ? [parsed] : [];
  })[0];
  expect(terminal).toMatchObject({
    type: "marimo-studio:view-error",
    revision: "presentation-revision",
    sessionId: "s_abc123",
    diagnostic: {
      code: "missing-variable",
      target: "summary.total",
    },
  });
  assert.equal(
    postMessage.mock.calls.some(([message]) => {
      const payload = jsonValueSchema.safeParse(message);
      return (
        payload.success &&
        previewMessageSchema.parse(payload.data).type === "marimo-studio:view-observation"
      );
    }),
    false,
  );
  globalThis.dispatchEvent(
    new MessageEvent("message", {
      origin: globalThis.location.origin,
      source: globalThis.parent,
      data: {
        type: "marimo-studio:observe-view",
        runtime: "server",
        lifecycleId: 1,
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "server-instance",
        requestId: "request-dashboard",
      },
    }),
  );
  await settleMutations();

  const observation = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const parsed = previewMessageSchema.parse(payload.data);
    return parsed?.type === "marimo-studio:view-observation" ? [parsed] : [];
  })[0];

  assert.deepEqual(observation, {
    type: "marimo-studio:view-observation",
    runtime: "server",
    lifecycleId: 1,
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
    runtimeInstance: "server-instance",
    sessionId: "s_abc123",
    requestId: "request-dashboard",
    query: "",
    projectionInstances: [
      {
        mountId: "site:value:summary.total",
        instanceId: observation?.projectionInstances[0]?.instanceId,
        target: "summary.total",
        runtimeCellId: "summary-cell",
        phase: "error",
        error: {
          code: "missing-variable",
          message: "summary is unavailable.",
        },
      },
    ],
  });
});

test("native output cannot impersonate projection or presentation diagnostics", async () => {
  document.body.innerHTML = `
    <div data-marimo-cell-output>
      <span
        mo-value="native"
        data-state="error"
        data-marimo-diagnostic-code="native-error"
        data-marimo-diagnostic-message="Native output failed."
      ></span>
      <div
        data-state="error"
        data-marimo-diagnostic-scope="presentation"
        data-marimo-diagnostic-code="fake-presentation-error"
        data-marimo-diagnostic-message="Fake presentation failure."
      ></div>
    </div>
  `;
  projectionHosts.connect();
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  expect(document.documentElement.dataset.marimoStudioState).toBe("ready");
  expect(globalThis.marimoStudio.diagnostics()).toEqual([]);
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
        lifecycleId: 1,
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "server-instance",
        requestId: "request-styles",
      },
    }),
  );
  await settleMutations();

  const observation = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const parsed = previewMessageSchema.parse(payload.data);
    return parsed?.type === "marimo-studio:view-observation" &&
      parsed.requestId === "request-styles"
      ? [parsed]
      : [];
  })[0];
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
        lifecycleId: 1,
        view: "dashboard",
        revision: "presentation-revision",
        runtimeInstance: "server-instance",
        requestId: "request-live-styles",
      },
    }),
  );
  await settleMutations();
  rejectGeneration(new Error("generator failed"));
  await settleMutations();

  const states = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const observation = previewMessageSchema.parse(payload.data);
    return observation?.type === "marimo-studio:view-observation" &&
      observation.requestId === "request-live-styles"
      ? [observation.state]
      : [];
  });
  expect(states).toEqual(["loading", "error"]);
  styles.disconnect();
});
