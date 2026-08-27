import type { QueryChangeMessage } from "@marimo-studio/protocol/preview-messages";

import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import { getMountConfig, getRuntimeConfig, hasRuntimeConfig } from "../runtime-config";
import { documentLifecycleEnvelope } from "./document-lifecycle-id.ts";
import { postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";

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
