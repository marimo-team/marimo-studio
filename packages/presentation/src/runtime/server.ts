import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import type { ServerRuntimeData } from "./server-config";

import { reconcileOutputReadResponse } from "../outputs/reconcile";
import { createServerOutputReader } from "../outputs/remote";
import { readServerValuesWithRetry } from "../values/remote";
import { mountSharedRuntime } from "./runtime";
import { createServerTransportURL } from "./transport";

export type { ServerRuntimeData } from "./server-config";

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
    transport: {
      kind: "server",
      url: new URL(data.url, globalThis.location.origin).toString(),
      serverToken: data.serverToken,
      transformTransportURL: createServerTransportURL(
        context.presentation.mode === "edit",
        data.file,
        data.serverInstance,
      ),
    },
    updateQuery: async () => {},
    valueReader:
      ({ sessionId }) =>
      (request, signal) =>
        readServerValuesWithRetry(sessionId, request, signal),
    outputReader: ({ sessionId }) =>
      createServerOutputReader(sessionId, reconcileOutputReadResponse),
  });
};
