import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import {
  createErrorToastingRequests,
  createNetworkRequests,
  getRuntimeManager,
  requestClientAtom,
  runtimeConfigAtom,
  store,
} from "@marimo-studio/marimo-frontend/runtime";

import { createServerOutputReader } from "../outputs/remote";
import { readServerValuesWithRetry } from "../values/remote";
import { mountSharedRuntime } from "./runtime";
import { configureServerTransport } from "./transport";

export interface ServerRuntimeData {
  url: string;
  serverToken: string;
  fileKey: string;
  file?: string;
  preserveSession: boolean;
}

export const mountServerRuntime = (
  context: RuntimeContext,
  data: ServerRuntimeData,
): RuntimeSession => {
  const initialMode = context.presentation.mode === "edit" ? "edit" : "read";
  const viewMode = context.presentation.mode === "edit" ? "present" : "read";
  return mountSharedRuntime(context.presentation, context.root, {
    id: "server",
    instance: context.presentation.runtime.instance,
    initialMode,
    viewMode,
    exposeSession: true,
    configureTransport() {
      store.set(runtimeConfigAtom, {
        url: new URL(data.url, globalThis.location.origin).toString(),
        lazy: false,
        serverToken: data.serverToken,
      });
      configureServerTransport(
        getRuntimeManager(),
        context.presentation.mode === "edit",
        data.file,
      );
      store.set(requestClientAtom, createErrorToastingRequests(createNetworkRequests()));
    },
    updateQuery: async () => {},
    valueReader: (sessionId) => (request, signal) =>
      readServerValuesWithRetry(sessionId, request, signal),
    outputReader: (sessionId) => createServerOutputReader(sessionId),
  });
};
