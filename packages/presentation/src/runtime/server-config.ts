import type { RuntimeEnvelope } from "@marimo-studio/protocol/runtime-config";

import { z } from "zod";

export const serverRuntimeDataSchema = z.strictObject({
  capabilityToken: z.string().min(1),
  sessionId: z.string().regex(/^s_[\da-z]{6}$/),
  serverInstance: z.string().min(1),
  storageScope: z.string().min(1),
  file: z.string().optional(),
  preserveSession: z.boolean(),
});

export type ServerRuntimeData = z.infer<typeof serverRuntimeDataSchema>;

const serverRuntimeUrlsSchema = z.strictObject({
  transport: z.string().min(1),
});

export interface ServerRuntime {
  readonly data: ServerRuntimeData;
  readonly urls: z.infer<typeof serverRuntimeUrlsSchema>;
}

export const parseServerRuntime = (runtime: RuntimeEnvelope): ServerRuntime => ({
  data: serverRuntimeDataSchema.parse(runtime.data),
  urls: serverRuntimeUrlsSchema.parse(runtime.urls),
});
