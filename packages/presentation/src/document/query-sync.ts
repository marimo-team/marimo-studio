import type { LocationChangeMessage } from "@marimo-studio/protocol/preview-messages";

import {
  PRESENTATION_REVISION_QUERY_PARAM,
  publicNotebookQuery,
} from "@marimo-studio/protocol/query";

import {
  getMountConfig,
  getRuntimeConfig,
  getSupportUrl,
  hasRuntimeConfig,
} from "../runtime-config";
import { documentLifecycleEnvelope } from "./document-lifecycle-id.ts";
import { postToStudioParent } from "./parent-bridge.ts";
import { studioOwned } from "./studio-ownership.ts";
import { setEditorBindingQuery } from "./view-navigation.ts";

const queryListeners = new Set<() => void>();

export const getDocumentQuery = (): string => publicNotebookQuery(globalThis.location.search);

export const subscribeDocumentQuery = (listener: () => void): (() => void) => {
  queryListeners.add(listener);
  return () => queryListeners.delete(listener);
};

export const bindRuntimeQueryHistory = (
  updateQuery: (query: string) => Promise<void>,
  reload: () => void = () => globalThis.location.reload(),
): (() => void) => {
  let active = true;
  let synchronized = getDocumentQuery();
  const stopTracking = subscribeDocumentQuery(() => {
    synchronized = getDocumentQuery();
  });
  // A fragment navigation also emits popstate and keeps the query. The capture
  // listener runs before query sync records the traversed location, so it
  // compares against the query of the last history write.
  const synchronize = () => {
    const query = getDocumentQuery();
    if (query === synchronized) {
      return;
    }
    synchronized = query;
    void updateQuery(query).catch(() => {
      if (active) {
        reload();
      }
    });
  };
  globalThis.addEventListener("popstate", synchronize, { capture: true });
  return () => {
    active = false;
    stopTracking();
    globalThis.removeEventListener("popstate", synchronize, { capture: true });
  };
};

export const startQuerySync = (): (() => void) => {
  const physicallyFramed = globalThis.parent !== globalThis.window;
  let reported: string | undefined;
  const notify = () => {
    queryListeners.forEach((listener) => listener());
    if (!studioOwned() && !physicallyFramed) {
      return;
    }
    const config = hasRuntimeConfig() ? getRuntimeConfig() : undefined;
    const message: LocationChangeMessage = {
      type: "marimo-studio:location-change",
      runtime: config?.runtime.id ?? getMountConfig().runtime,
      ...documentLifecycleEnvelope(),
      ...(config && { view: config.view }),
      query: getDocumentQuery(),
      hash: globalThis.location.hash,
    };
    // A fragment navigation emits popstate and hashchange for one location.
    const key = JSON.stringify(message);
    if (key === reported) {
      return;
    }
    reported = key;
    postToStudioParent(message);
  };
  const pushState = globalThis.history.pushState.bind(globalThis.history);
  const replaceState = globalThis.history.replaceState.bind(globalThis.history);

  const preserveExactRevision = (url: string | URL | null | undefined) => {
    if (url == null) {
      return url;
    }
    const current = new URL(globalThis.location.href);
    const target = new URL(url, current);
    const revision = current.searchParams.get(PRESENTATION_REVISION_QUERY_PARAM);
    if (target.origin === current.origin && target.pathname === current.pathname) {
      if (revision) {
        target.searchParams.set(PRESENTATION_REVISION_QUERY_PARAM, revision);
      }
      setEditorBindingQuery(target, getMountConfig().clientId, getSupportUrl());
    }
    return target.href;
  };

  // Marimo applies mo.query_params() updates, and hash routers apply fragment
  // changes, through same-document history writes, which emit no events.
  const wrappedPush: History["pushState"] = (...arguments_) => {
    pushState(arguments_[0], arguments_[1], preserveExactRevision(arguments_[2]));
    notify();
  };
  const wrappedReplace: History["replaceState"] = (...arguments_) => {
    replaceState(arguments_[0], arguments_[1], preserveExactRevision(arguments_[2]));
    notify();
  };
  globalThis.history.pushState = wrappedPush;
  globalThis.history.replaceState = wrappedReplace;
  globalThis.addEventListener("popstate", notify);
  globalThis.addEventListener("hashchange", notify);
  notify();
  return () => {
    globalThis.removeEventListener("popstate", notify);
    globalThis.removeEventListener("hashchange", notify);
    if (globalThis.history.pushState === wrappedPush) globalThis.history.pushState = pushState;
    if (globalThis.history.replaceState === wrappedReplace)
      globalThis.history.replaceState = replaceState;
  };
};
