import { z } from "zod";

export const serverRuntimeDataSchema = z.object({
  url: z.string(),
  serverToken: z.string(),
  serverInstance: z.string().min(1),
  fileKey: z.string(),
  file: z.string().optional(),
  preserveSession: z.boolean(),
});

export type ServerRuntimeData = z.infer<typeof serverRuntimeDataSchema>;
