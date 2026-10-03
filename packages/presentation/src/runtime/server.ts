import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import { reconcileOutputReadResponse } from "../outputs/reconcile";
import { createServerOutputReader } from "../outputs/remote";
import { getMountConfig } from "../runtime-config/index.ts";
import { readServerValuesWithRetry } from "../values/remote";
import { mountSharedRuntime } from "./runtime";
import { parseServerRuntime, type ServerRuntime } from "./server-config";
import { createServerTransportURL } from "./transport";

export type { ServerRuntimeData } from "./server-config";

const serverTransport = (
  presentation: RuntimeContext["presentation"],
  { data, urls }: ServerRuntime,
) => {
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
    url: urls.transport,
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
  runtime: ServerRuntime,
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
    transport: serverTransport(context.presentation, runtime),
    serverTransport(next) {
      return serverTransport(next, parseServerRuntime(next.runtime));
    },
    updateQuery: async () => {},
    valueReader: () => (request, signal) => readServerValuesWithRetry(request, signal),
    outputReader: () => createServerOutputReader(reconcileOutputReadResponse),
  });
};
