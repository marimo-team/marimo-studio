import type { ViewStateMessage } from "@marimo-studio/protocol/preview-messages";

import { toBrowserDiagnostics } from "../readiness-diagnostics.ts";
import { readiness } from "../readiness.ts";
import { renderedViewDiagnostics } from "../rendered-view-state.ts";
import {
  getMountConfig,
  getRuntimeConfig,
  hasRuntimeConfig,
  subscribeRuntimeConfig,
} from "../runtime-config/index.ts";
import { documentLifecycleEnvelope } from "./document-lifecycle-id.ts";
import { postToStudioParent } from "./parent-bridge.ts";

const post = (state: Pick<ViewStateMessage, "diagnostics" | "revision" | "state">): void => {
  postToStudioParent({
    type: "marimo-studio:view-state",
    runtime: hasRuntimeConfig() ? getRuntimeConfig().runtime.id : getMountConfig().runtime,
    ...documentLifecycleEnvelope(),
    ...state,
  });
};

/**
 * Mirrors this document's readiness to a trusted standalone wrapper, whose
 * `<html>` is what top-level browser automation can observe. The final report
 * leaves the wrapper `loading` until the next document reports.
 */
export const startViewStateReport = (): (() => void) => {
  let reported: string | undefined;
  const report = (): void => {
    const state = {
      state: readiness.snapshot().page,
      ...(hasRuntimeConfig() && { revision: getRuntimeConfig().revision }),
      diagnostics: toBrowserDiagnostics(renderedViewDiagnostics()),
    };
    const serialized = JSON.stringify(state);
    if (serialized !== reported) {
      reported = serialized;
      post(state);
    }
  };
  const stopReadiness = readiness.subscribe(report);
  const stopRuntimeConfig = subscribeRuntimeConfig(report);
  // A host can change its diagnostic while its state stays `error`.
  const hostDiagnostics = new MutationObserver(report);
  hostDiagnostics.observe(document.documentElement, {
    attributes: true,
    attributeFilter: [
      "data-marimo-diagnostic-code",
      "data-marimo-diagnostic-message",
      "data-marimo-diagnostic-hint",
    ],
    subtree: true,
  });
  report();
  return () => {
    stopReadiness();
    stopRuntimeConfig();
    hostDiagnostics.disconnect();
    post({ state: "loading", diagnostics: [] });
  };
};
