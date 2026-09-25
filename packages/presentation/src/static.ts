import type { RuntimeRegistry } from "@marimo-studio/runtime";

import { documentBase } from "./document/base.ts";
import { onFinalPageHide } from "./document/page-lifecycle.ts";
import { startQuerySync } from "./document/query-sync.ts";
import { errorMessage } from "./errors.ts";
import { startPresentationObservers, stopPresentationObservers } from "./observers.ts";
import { projectionHosts } from "./projections/host-runtime.ts";
import { setRuntimeConnectionState } from "./rendered-view-observer.ts";
import { loadRuntimeConfig } from "./runtime-config/index.ts";
import {
  disposeConfiguredRuntime,
  mountConfiguredRuntime,
  updateConfiguredRuntimeQuery,
} from "./runtime/coordinator.ts";
import "./runtime/style.css";

declare global {
  interface Window {
    __MARIMO_STUDIO_RUNTIME_STATE__?: "booting" | "failed" | "mounted";
  }
}

export const startStaticPresentation = (registry: RuntimeRegistry): void => {
  const lifetime = new AbortController();
  window.__MARIMO_STUDIO_RUNTIME_STATE__ = "booting";
  documentBase.start(document.baseURI);
  startQuerySync();
  onFinalPageHide(() => {
    lifetime.abort(new DOMException("Static presentation retired", "AbortError"));
    documentBase.stop();
    stopPresentationObservers();
    projectionHosts.disconnect();
    disposeConfiguredRuntime();
  });

  void (async () => {
    const config = await loadRuntimeConfig(undefined, lifetime.signal);
    projectionHosts.register();
    projectionHosts.connect();
    startPresentationObservers(updateConfiguredRuntimeQuery);
    const runtimeRoot = document.querySelector<HTMLElement>("#marimo-runtime-root");
    if (!runtimeRoot) {
      throw new Error("Missing #marimo-runtime-root");
    }
    await mountConfiguredRuntime(registry, config, runtimeRoot);
    lifetime.signal.throwIfAborted();
    window.__MARIMO_STUDIO_RUNTIME_STATE__ = "mounted";
  })().catch((cause: unknown) => {
    if (lifetime.signal.aborted) {
      return;
    }
    window.__MARIMO_STUDIO_RUNTIME_STATE__ = "failed";
    setRuntimeConnectionState("error", {
      code: "static-runtime-failed",
      message: errorMessage(cause),
      hint: "Rebuild the exported view, then reload the page.",
    });
    console.error("marimo-studio static runtime error", cause);
  });
};
