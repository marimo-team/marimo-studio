import type { QueryChangeMessage } from "@marimo-studio/protocol/preview-messages";

import { publicNotebookQuery } from "@marimo-studio/protocol/query";

export const startQuerySync = (): void => {
  const frame = globalThis.frameElement;
  if (frame?.localName !== "iframe" || !frame.hasAttribute("data-preview-frame")) {
    return;
  }
  const notify = () => {
    const message: QueryChangeMessage = {
      type: "marimo-studio:query-change",
      query: publicNotebookQuery(globalThis.location.search),
    };
    globalThis.parent.postMessage(message, globalThis.location.origin);
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
