import htmx from "htmx.org";

import { registerMarimoCellElement } from "./cell-host";
import { setRuntimeConnectionState, startReadiness } from "./readiness";
import {
  commitRuntimeConfig,
  fetchRuntimeConfigWithRetry,
  getRuntimeConfig,
  getSupportUrl,
  loadRuntimeConfig,
} from "./runtime-config";
import {
  finishSessionRefresh,
  prepareSessionRefresh,
  rememberSession,
} from "./session-preservation";
import { startValueBindings } from "./value-bindings";

declare global {
  interface Window {
    htmx: typeof htmx;
    __MARIMO_STUDIO_SESSION_ID__?: string;
  }
}

const showRuntimeError = (error: unknown) => {
  setRuntimeConnectionState("error");
  console.error("marimo-studio runtime error", error);
};

const bootstrap = async () => {
  startReadiness();
  registerMarimoCellElement();
  (globalThis as typeof globalThis & Window).htmx = htmx;

  let config = await loadRuntimeConfig();
  const resumingDocument = prepareSessionRefresh(config);
  if (resumingDocument) {
    config = commitRuntimeConfig(
      await fetchRuntimeConfigWithRetry(getSupportUrl()),
    );
    document.addEventListener(
      "marimo-studio:runtime-ready",
      () => finishSessionRefresh(),
      { once: true },
    );
  }
  startValueBindings();
  const runtimeRoot = document.querySelector<HTMLElement>(
    "#marimo-runtime-root",
  );
  if (!runtimeRoot) {
    throw new Error("Missing #marimo-runtime-root");
  }
  // Marimo selects its module-level session ID when this adapter loads.
  const { mountMarimoRuntime } = await import("./marimo-adapter/runtime");
  const sessionId = mountMarimoRuntime(config, runtimeRoot);
  rememberSession(config, sessionId);
  globalThis.addEventListener(
    "pagehide",
    () => rememberSession(getRuntimeConfig(), sessionId),
    { once: true },
  );
};

void bootstrap().catch(showRuntimeError);
