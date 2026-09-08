import { z } from "zod";

import type { JsonValue } from "./runtime-config";

export const hostSessionTransitionSchema = z.enum(["complete", "native", "reset", "studio"]);

export const hostSessionConfigSchema = z.object({
  schema: z.literal(1),
  capability: z.string().regex(/^[a-f0-9]{64}$/),
  session: z.string().regex(/^s_[a-z0-9]{6}$/),
  handoff: z.string(),
  resume: z.string(),
  transition: hostSessionTransitionSchema,
});

export type HostSessionTransition = z.infer<typeof hostSessionTransitionSchema>;
export type HostSessionConfig = z.infer<typeof hostSessionConfigSchema>;

export const parseHostSessionConfig = (value: JsonValue): HostSessionConfig =>
  hostSessionConfigSchema.parse(value);
