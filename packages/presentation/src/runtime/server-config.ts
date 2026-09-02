import { z } from "zod";

export const serverRuntimeDataSchema = z.strictObject({
  url: z.string(),
  capabilityToken: z.string().min(1),
  sessionId: z.string().regex(/^s_[\da-z]{6}$/),
  serverInstance: z.string().min(1),
  fileKey: z.string(),
  file: z.string().optional(),
  preserveSession: z.boolean(),
});

export type ServerRuntimeData = z.infer<typeof serverRuntimeDataSchema>;
