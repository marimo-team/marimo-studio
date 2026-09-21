import "./framed-document.ts";
import { parsePreviewMessage } from "@marimo-studio/protocol/preview-messages";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import assert from "node:assert/strict";
import { afterEach, test, vi } from "vite-plus/test";

import { activeDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import { startPresentationObservers, stopPresentationObservers } from "../src/observers.ts";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import { toBrowserDiagnostics } from "../src/readiness-diagnostics.ts";
import { pageReadinessState, ReadinessController } from "../src/readiness.ts";
import {
  announceRenderedViewReady,
  setRuntimeConnectionState,
} from "../src/rendered-view-observer.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { valueCellPhase } from "../src/runtime/value-cell-state.ts";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures.ts";

const mountConfig = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  clientId: "client-123456789",
  lifecycleId: 7,
} as const;

globalThis.__MARIMO_MOUNT_CONFIG__ = mountConfig;

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

afterEach(() => {
  stopPresentationObservers();
  projectionHosts.disconnect();
  globalThis.history.replaceState({}, "", "/");
  globalThis.__MARIMO_MOUNT_CONFIG__ = mountConfig;
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = undefined;
  vi.restoreAllMocks();
});

const valueCell = (
  overrides: Partial<Parameters<typeof valueCellPhase>[0]> = {},
): Parameters<typeof valueCellPhase>[0] => ({
  runtimeReady: true,
  hasCell: true,
  disabled: false,
  status: "idle",
  version: 1,
  errored: false,
  stale: false,
  deliveryTimedOut: false,
  ...overrides,
});

test("page readiness accounts for pending and retained hosts", () => {
  assert.deepEqual(pageReadinessState("ready", ["error", "loading"]), "loading");
  assert.deepEqual(pageReadinessState("ready", ["error", "ready"]), "error");
  assert.deepEqual(pageReadinessState("ready", ["stale", "ready"]), "loading");
  assert.deepEqual(pageReadinessState("ready", ["ready"], "loading"), "loading");
  assert.deepEqual(pageReadinessState("ready", ["ready"], "error"), "error");
});

test("runtime startup and document refresh owners settle independently", () => {
  const controller = new ReadinessController();
  controller.start();
  controller.setRuntime("ready");
  controller.setHosts(["ready"]);
  const documentClaim = controller.beginPresentation("document");
  const runtimeClaim = controller.beginPresentation("runtime");

  controller.setPresentation(documentClaim, "ready");
  assert.equal(controller.snapshot().page, "loading");
  controller.setPresentation(runtimeClaim, "ready");
  assert.equal(controller.snapshot().page, "ready");

  const stale = controller.beginPresentation("document");
  const current = controller.beginPresentation("document");
  controller.setPresentation(stale, "ready");
  assert.equal(controller.snapshot().page, "loading");
  controller.setPresentation(current, "ready");
  assert.equal(controller.snapshot().page, "ready");
});

test("failed runtime startup settles readiness and retains the runtime diagnostic", async () => {
  const controller = new ReadinessController();
  controller.start();
  const claim = controller.beginPresentation("runtime");
  controller.setRuntime("ready");
  const settled = controller.ready();
  controller.setPresentation(claim, "error");
  const diagnostic = {
    scope: "runtime" as const,
    severity: "error" as const,
    code: "runtime-bootstrap-failed",
    message: "The notebook server disconnected.",
    hint: "Start the notebook server and retry the preview.",
    view: "dashboard",
  };
  controller.setRuntime("error", diagnostic);

  await settled;
  assert.equal(controller.snapshot().page, "error");
  assert.deepEqual(controller.snapshot().runtimeDiagnostic, diagnostic);
});

test("browser evidence reports deterministic diagnostic truncation", () => {
  const diagnostics = Array.from({ length: 205 }, (_, index) => ({
    scope: "presentation" as const,
    code: `diagnostic-${index}`,
    severity: "error" as const,
    message: `Failure ${index}`,
    hint: "Fix it.",
    view: "dashboard",
  }));

  const browser = toBrowserDiagnostics(diagnostics);

  assert.equal(browser.length, 200);
  assert.deepEqual(browser[199], {
    code: "browser-diagnostics-truncated",
    severity: "error",
    message: "6 additional browser diagnostics were omitted.",
    hint: "Fix repeated rendered-view errors, then rerun validation.",
    view: "dashboard",
    scope: "presentation",
  });
});

test("WASM readiness omits an unavailable session from its preview message", async () => {
  globalThis.__MARIMO_MOUNT_CONFIG__ = { ...mountConfig, runtime: "wasm" };
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");

  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  const ready = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const parsed = parsePreviewMessage(payload.data);
    return parsed?.type === "marimo-studio:view-ready" ? [parsed] : [];
  });
  assert.deepEqual(ready, [
    {
      type: "marimo-studio:view-ready",
      runtime: "wasm",
      lifecycleId: 7,
      view: "dashboard",
      revision: "presentation-revision",
    },
  ]);
});

test("readiness acknowledges the active preview switch", async () => {
  globalThis.history.replaceState({}, "", "/?marimo_studio_lifecycle=7");
  const postMessage = vi.spyOn(globalThis.parent, "postMessage");

  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  const ready = postMessage.mock.calls.flatMap(([message]) => {
    const payload = jsonValueSchema.safeParse(message);
    if (!payload.success) {
      return [];
    }
    const parsed = parsePreviewMessage(payload.data);
    return parsed?.type === "marimo-studio:view-ready" ? [parsed] : [];
  });
  assert.equal(
    ready.some((message) => message.lifecycleId === 7),
    true,
  );
  postMessage.mockClear();
  announceRenderedViewReady();
  assert.equal(
    postMessage.mock.calls.some(([message]) => {
      const payload = jsonValueSchema.safeParse(message);
      if (!payload.success) {
        return false;
      }
      const parsed = parsePreviewMessage(payload.data);
      return parsed?.type === "marimo-studio:view-ready" && parsed.lifecycleId === 7;
    }),
    true,
  );
});

test("document identity survives browser URL canonicalization", () => {
  globalThis.history.replaceState({}, "", "/?marimo_studio_lifecycle=7");
  assert.equal(activeDocumentLifecycleId(), 7);

  globalThis.history.replaceState({}, "", "/?runtime=wasm");
  assert.equal(activeDocumentLifecycleId(), 7);
});

test("a stale value opens a new idle batch while its snapshot remains visible", async () => {
  commitRuntimeConfig(projectionRuntimeConfig([projectionRequest("report", "value")]));
  document.body.innerHTML = `<span mo-value="report" data-marimo-studio-site="site:value:report"></span>`;
  const source = document.querySelector<HTMLElement>("[mo-value]")!;
  projectionHosts.connect();
  source.dataset.state = "ready";
  let idleEvents = 0;
  document.addEventListener("marimo-studio:idle", () => idleEvents++);
  startPresentationObservers(async () => {});
  setRuntimeConnectionState("ready");
  await settleMutations();

  const initialEvents = idleEvents;

  source.dataset.state = "stale";
  await settleMutations();
  let resolved = false;
  const ready = globalThis.marimoStudio.ready().then(() => {
    resolved = true;
  });
  await Promise.resolve();
  assert.equal(resolved, false);
  assert.equal(idleEvents, initialEvents);
  assert.equal(document.documentElement.dataset.marimoStudioState, "loading");

  source.dataset.state = "ready";
  await ready;
  assert.equal(idleEvents, initialEvents + 1);
});

test("value cell phases follow the defining Marimo cell", () => {
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        hasCell: false,
        status: "missing",
        version: null,
      }),
    ),
    "loading",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        disabled: true,
        version: null,
      }),
    ),
    "error",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        runtimeReady: false,
        hasCell: false,
        status: "missing",
        version: null,
      }),
    ),
    "loading",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        hasCell: false,
        status: "missing",
        version: null,
        deliveryTimedOut: true,
      }),
    ),
    "error",
  );
  assert.deepEqual(
    valueCellPhase(
      valueCell({
        stale: true,
      }),
    ),
    "stale",
  );
  assert.deepEqual(valueCellPhase(valueCell({ version: 2 })), "ready");
});

test("an unrelated loading owner does not erase an unresolved disconnect diagnostic", () => {
  const controller = new ReadinessController();
  controller.setRuntime("ready");
  const development = controller.beginPresentation("development");
  const diagnostic = {
    scope: "presentation" as const,
    severity: "warning" as const,
    code: "development-disconnected",
    message: "Live updates disconnected.",
    hint: "Reconnect the server.",
    view: "dashboard",
  };
  controller.setPresentation(development, "loading", diagnostic);
  const document = controller.beginPresentation("document");
  assert.equal(controller.snapshot().presentationDiagnostic, diagnostic);
  controller.setPresentation(development, "ready");
  assert.equal(controller.snapshot().page, "loading");
  assert.equal(controller.snapshot().presentationDiagnostic, undefined);
  controller.setPresentation(document, "ready");
  assert.equal(controller.snapshot().page, "ready");
});
