import htmx from "htmx.org";

import { registerMarimoCellElement } from "./cell-host";
import { setRuntimeConnectionState, startReadiness } from "./readiness";
import {
  commitRuntimeConfig,
  fetchRuntimeConfigForRevision,
  getRuntimeConfig,
  getSupportUrl,
  loadRuntimeConfig,
  RuntimeConfigRequestError,
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
    __MARIMO_STUDIO_RUNTIME_STATE__?: "booting" | "failed" | "mounted";
  }
}

const browser = globalThis as typeof globalThis & Window;
browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "booting";

const showRuntimeError = (error: unknown) => {
  browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "failed";
  setRuntimeConnectionState("error", {
    code: error instanceof RuntimeConfigRequestError
      ? error.code
      : "runtime-bootstrap-failed",
    message: error instanceof Error ? error.message : String(error),
    hint: error instanceof RuntimeConfigRequestError
      ? error.hint
      : "Reload the view after the runtime is available.",
  });
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
      await fetchRuntimeConfigForRevision(
        getSupportUrl(),
        config.revision,
      ),
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
  browser.__MARIMO_STUDIO_RUNTIME_STATE__ = "mounted";
  rememberSession(config, sessionId);
  globalThis.addEventListener(
    "pagehide",
    () => rememberSession(getRuntimeConfig(), sessionId),
    { once: true },
  );
};

const start = () => {
  void bootstrap().catch((error: unknown) => {
    if (error instanceof RuntimeConfigRequestError && error.transient) {
      setRuntimeConnectionState("connecting", {
        code: error.code,
        message: error.message,
        hint: error.hint || "Wait for the notebook session to settle.",
      });
      if (error.code === "presentation-revision-mismatch") {
        setTimeout(() => globalThis.location.reload(), 250);
      } else {
        setTimeout(start, 1_000);
      }
      return;
    }
    showRuntimeError(error);
  });
};

start();
