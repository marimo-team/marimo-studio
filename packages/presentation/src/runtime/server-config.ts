import { z } from "zod";

export const serverRuntimeDataSchema = z.object({
  url: z.string(),
  serverToken: z.string(),
  fileKey: z.string(),
  file: z.string().optional(),
  preserveSession: z.boolean(),
});

export type ServerRuntimeData = z.infer<typeof serverRuntimeDataSchema>;
