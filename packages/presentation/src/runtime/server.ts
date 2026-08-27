import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import { reconcileOutputReadResponse } from "../outputs/reconcile";
import { createServerOutputReader } from "../outputs/remote";
import { getMountConfig } from "../runtime-config/index.ts";
import { readServerValuesWithRetry } from "../values/remote";
import { mountSharedRuntime } from "./runtime";
import { serverRuntimeDataSchema, type ServerRuntimeData } from "./server-config";
import { createServerTransportURL } from "./transport";

export type { ServerRuntimeData } from "./server-config";

const serverTransport = (presentation: RuntimeContext["presentation"], data: ServerRuntimeData) => {
  if (!presentation.presentationSessionId) {
    throw new Error("The server runtime requires a presentation session");
  }
  const mount = getMountConfig();
  if (mount.sessionId !== presentation.presentationSessionId) {
    throw new Error("The presentation session does not match its mount authority");
  }
  if (mount.runtimeSessionId !== data.sessionId) {
    throw new Error("The server runtime session does not match its mount authority");
  }
  return {
    kind: "server" as const,
    presentationSessionId: presentation.presentationSessionId,
    url: new URL(data.url, globalThis.location.origin).toString(),
    serverToken: data.capabilityToken,
    transformTransportURL: createServerTransportURL(
      presentation.mode === "edit",
      data.file,
      data.serverInstance,
      mount.sessionId,
    ),
  };
};

export const mountServerRuntime = (
  context: RuntimeContext,
  data: ServerRuntimeData,
): RuntimeSession => {
  const initialMode = context.presentation.mode === "edit" ? "edit" : "read";
  const viewMode = context.presentation.mode === "edit" ? "present" : "read";
  return mountSharedRuntime(context.presentation, context.root, {
    autoInstantiate: true,
    id: "server",
    instance: context.presentation.runtime.instance,
    initialMode,
    viewMode,
    exposeSession: true,
    transport: serverTransport(context.presentation, data),
    serverTransport(next) {
      return serverTransport(next, serverRuntimeDataSchema.parse(next.runtime.data));
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
