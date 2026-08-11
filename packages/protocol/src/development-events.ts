import { z } from "zod";

import { jsonCodec } from "./json.ts";
import { runtimeIdSchema } from "./runtime-config";

export const shellChangeKindSchema = z.enum(["css", "html", "runtime", "views"]);
const shellChangeSchema = z.object({ kind: shellChangeKindSchema });
const shellChangeCodec = jsonCodec(shellChangeSchema);

export type ShellChangeKind = z.infer<typeof shellChangeKindSchema>;

export const parseShellChange = (source: string): ShellChangeKind | undefined => {
  const result = shellChangeCodec.safeDecode(source);
  return result.success ? result.data.kind : undefined;
};

const activeViewSchema = z
  .object({
    schema: z.literal(1),
    generation: z.int().nonnegative(),
    view: z.string().min(1),
  })
  .strict();
const activeViewCodec = jsonCodec(activeViewSchema);

export type ActiveViewRequest = z.infer<typeof activeViewSchema>;

export const parseActiveViewRequest = (source: string): ActiveViewRequest | undefined => {
  const result = activeViewCodec.safeDecode(source);
  return result.success ? result.data : undefined;
};

const editorSessionBindingSchema = z
  .object({
    schema: z.literal(1),
    generation: z.int().positive(),
    sessionId: z.string().min(1),
    replaced: z.boolean(),
  })
  .strict();
const editorSessionBindingCodec = jsonCodec(editorSessionBindingSchema);

export type EditorSessionBinding = z.infer<typeof editorSessionBindingSchema>;

export const parseEditorSessionBinding = (source: string): EditorSessionBinding | undefined => {
  const result = editorSessionBindingCodec.safeDecode(source);
  return result.success ? result.data : undefined;
};

const observeViewSchema = z
  .object({
    schema: z.literal(1),
    requestId: z.string().min(1),
    view: z.string().min(1),
    runtime: runtimeIdSchema,
    runtimeInstance: z.string().min(1),
    revision: z.string().min(1),
    activeViewGeneration: z.int().nonnegative().optional(),
  })
  .strict();
const observeViewCodec = jsonCodec(observeViewSchema);

export type ObserveViewRequest = z.infer<typeof observeViewSchema>;

export const parseObserveViewRequest = (source: string): ObserveViewRequest | undefined => {
  const result = observeViewCodec.safeDecode(source);
  return result.success ? result.data : undefined;
};
