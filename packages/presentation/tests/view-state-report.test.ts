import "./framed-document.ts";
import { parsePreviewMessage } from "@marimo-studio/protocol/preview-messages";
import { afterEach, beforeEach, expect, test, vi } from "vite-plus/test";

import { runtimeConfig } from "./runtime-fixtures.ts";

const standaloneMount = {
  supportUrl: "http://localhost:3000/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
} as const;

let stopReport: (() => void) | undefined;

const reports = () =>
  vi.mocked(globalThis.parent.postMessage).mock.calls.flatMap(([message]) => {
    const parsed = parsePreviewMessage(message);
    return parsed?.type === "marimo-studio:view-state" ? [parsed] : [];
  });

// Readiness and runtime configuration are per-document singletons, so each
// test loads the modules as a new document does.
const newDocument = async () => {
  vi.resetModules();
  const [report, readinessModule, observer, config, hosts] = await Promise.all([
    import("../src/document/view-state-report.ts"),
    import("../src/readiness.ts"),
    import("../src/rendered-view-observer.ts"),
    import("../src/runtime-config/index.ts"),
    import("../src/projections/host-runtime.ts"),
  ]);
  return { ...report, ...readinessModule, ...observer, ...config, ...hosts };
};

beforeEach(() => {
  globalThis.__MARIMO_MOUNT_CONFIG__ = standaloneMount;
});

afterEach(() => {
  stopReport?.();
  stopReport = undefined;
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("reports each page state with the committed revision", async () => {
  const view = await newDocument();
  stopReport = view.startViewStateReport();

  view.setRuntimeConnectionState("ready");
  view.commitRuntimeConfig(runtimeConfig());
  const buildClaim = view.beginPresentationRefresh("build");
  view.setPresentationRefreshState(buildClaim, "ready");

  expect(reports().map(({ state, revision }) => ({ state, revision }))).toEqual([
    { state: "connecting", revision: undefined },
    { state: "ready", revision: undefined },
    { state: "ready", revision: runtimeConfig().revision },
    { state: "loading", revision: runtimeConfig().revision },
    { state: "ready", revision: runtimeConfig().revision },
  ]);
});

test("a failed build reports ready with its error beside the previous build", async () => {
  const view = await newDocument();
  stopReport = view.startViewStateReport();

  view.setRuntimeConnectionState("ready");
  view.commitRuntimeConfig(runtimeConfig());
  const buildClaim = view.beginPresentationRefresh("build");
  view.setPresentationRefreshState(buildClaim, "ready", {
    scope: "presentation",
    code: "view-build-failed",
    severity: "error",
    message: "Latest build failed. Showing the previous build.",
    hint: "Fix the view source, then build it again.",
    view: "dashboard",
  });

  expect(reports().at(-1)).toMatchObject({
    state: "ready",
    revision: runtimeConfig().revision,
    diagnostics: [{ code: "view-build-failed", severity: "error" }],
  });
});

test("a runtime failure before the rendered view observer starts reports its diagnostic", async () => {
  const view = await newDocument();
  stopReport = view.startViewStateReport();

  view.setRuntimeConnectionState("error", {
    code: "runtime-bootstrap-failed",
    message: "The runtime could not start.",
    hint: "Reload the view after the runtime is available.",
  });

  expect(reports().at(-1)).toMatchObject({
    state: "error",
    diagnostics: [{ code: "runtime-bootstrap-failed", severity: "error" }],
  });
});

test("a host diagnostic change reports while the page state holds", async () => {
  const view = await newDocument();
  const host = document.createElement("marimo-cell");
  host.setAttribute("name", "controls");
  host.dataset.marimoDiagnosticCode = "runtime-cell-not-received";
  host.dataset.marimoDiagnosticMessage = "First failure";
  document.body.append(host);
  vi.spyOn(view.projectionHosts, "hosts").mockReturnValue([host]);
  stopReport = view.startViewStateReport();
  const before = reports().length;

  host.dataset.marimoDiagnosticMessage = "Second failure";

  await expect.poll(() => reports().at(-1)?.diagnostics[0]?.message).toBe("Second failure");
  expect(reports()).toHaveLength(before + 1);
});

test("an unchanged state posts one report", async () => {
  const view = await newDocument();
  stopReport = view.startViewStateReport();

  view.setRuntimeConnectionState("ready");
  view.setRuntimeConnectionState("ready");

  expect(reports().map(({ state }) => state)).toEqual(["connecting", "ready"]);
});

test("leaving the document reports loading without its revision or diagnostics", async () => {
  const view = await newDocument();
  const stop = view.startViewStateReport();
  view.setRuntimeConnectionState("ready");
  view.commitRuntimeConfig(runtimeConfig());

  stop();

  expect(reports().at(-1)).toMatchObject({ state: "loading", diagnostics: [] });
  expect(reports().at(-1)?.revision).toBeUndefined();
});

test("each standalone document reports under its own lifecycle", async () => {
  const reportedLifecycle = async () => {
    const view = await newDocument();
    const stop = view.startViewStateReport();
    const lifecycleId = reports().at(-1)?.lifecycleId;
    stop();
    return lifecycleId;
  };

  const first = await reportedLifecycle();
  const second = await reportedLifecycle();

  expect(first).not.toBe(second);
  expect(Number.isSafeInteger(first) && Number(first) > 0).toBe(true);
});

test("a Studio-assigned lifecycle identifies the document", async () => {
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    ...standaloneMount,
    clientId: "client-123456789",
    lifecycleId: 7,
  };
  const view = await newDocument();

  stopReport = view.startViewStateReport();

  expect(reports().at(-1)?.lifecycleId).toBe(7);
});
