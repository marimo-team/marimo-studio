import type { QueryChangeMessage } from "@marimo-studio/protocol/preview-messages";

import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import { getMountConfig, getRuntimeConfig, hasRuntimeConfig } from "../runtime-config";
import { documentLifecycleEnvelope } from "./document-lifecycle-id.ts";
import { postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";

export const bindRuntimeQueryHistory = (
  updateQuery: (query: string) => Promise<void>,
  reload: () => void = () => globalThis.location.reload(),
): (() => void) => {
  let active = true;
  const synchronize = () => {
    void updateQuery(publicNotebookQuery(globalThis.location.search)).catch(() => {
      if (active) {
        reload();
      }
    });
  };
  globalThis.addEventListener("popstate", synchronize);
  return () => {
    active = false;
    globalThis.removeEventListener("popstate", synchronize);
  };
};

interface StandaloneQuerySyncOptions {
  readonly applyInitial?: boolean;
}

export const startQuerySync = (): void => {
  const physicallyFramed = globalThis.parent !== globalThis.window;
  if (!studioOwned() && !physicallyFramed) {
    return;
  }
  const notify = () => {
    const message: QueryChangeMessage = {
      type: "marimo-studio:query-change",
      runtime: hasRuntimeConfig() ? getRuntimeConfig().runtime.id : getMountConfig().runtime,
      ...documentLifecycleEnvelope(),
      query: publicNotebookQuery(globalThis.location.search),
    };
    postToStudioParent(message);
  };
  const pushState = globalThis.history.pushState.bind(globalThis.history);
  const replaceState = globalThis.history.replaceState.bind(globalThis.history);

  // Marimo applies mo.query_params() updates through same-document history
  // writes, which do not emit popstate events.
  globalThis.history.pushState = (...arguments_) => {
    pushState(...arguments_);
    notify();
  };
  globalThis.history.replaceState = (...arguments_) => {
    replaceState(...arguments_);
    notify();
  };
  globalThis.addEventListener("popstate", notify);
  notify();
};

export const startStandaloneQuerySync = async (
  updateQuery: (query: string) => Promise<void>,
  options: StandaloneQuerySyncOptions = {},
): Promise<() => void> => {
  const frame = globalThis.frameElement;
  if (frame?.localName === "iframe" && frame.hasAttribute("data-preview-frame")) {
    return () => {};
  }
  const apply = () => updateQuery(publicNotebookQuery(globalThis.location.search));
  const applyLater = () => {
    void apply().catch((error) => {
      console.warn("Standalone Zero-Python query update failed", error);
    });
  };
  if (options.applyInitial !== false) {
    await apply();
  }
  const pushState = globalThis.history.pushState.bind(globalThis.history);
  const replaceState = globalThis.history.replaceState.bind(globalThis.history);
  globalThis.history.pushState = (...arguments_) => {
    pushState(...arguments_);
    applyLater();
  };
  globalThis.history.replaceState = (...arguments_) => {
    replaceState(...arguments_);
    applyLater();
  };
  globalThis.addEventListener("popstate", applyLater);
  let running = true;
  return () => {
    if (!running) {
      return;
    }
    running = false;
    globalThis.history.pushState = pushState;
    globalThis.history.replaceState = replaceState;
    globalThis.removeEventListener("popstate", applyLater);
  };
};
