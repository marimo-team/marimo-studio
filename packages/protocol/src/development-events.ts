import { z } from "zod";

import type { BrowserMessageInput } from "./frame-bridge.ts";

import { jsonCodec } from "./json.ts";
import { type JsonValue, runtimeIdSchema } from "./runtime-config";
import { viewNameSchema } from "./views.ts";

export const workspaceChangeKindSchema = z.enum(["project", "build", "presentation", "views"]);
const workspaceChangeSchema = z.object({ kind: workspaceChangeKindSchema });
const workspaceChangeCodec = jsonCodec(workspaceChangeSchema);

export type WorkspaceChangeKind = z.infer<typeof workspaceChangeKindSchema>;

const activationAckResponseSchema = z
  .object({
    schema: z.literal(1),
    outcome: z.enum(["applied", "retryable", "rejected"]),
  })
  .strict();

export type ActivationAckResponse = z.infer<typeof activationAckResponseSchema>;

export const parseActivationAckResponse = (
  payload: JsonValue,
): ActivationAckResponse | undefined => {
  const result = activationAckResponseSchema.safeParse(payload);
  return result.success ? result.data : undefined;
};

export const parseWorkspaceChange = (source: string): WorkspaceChangeKind | undefined => {
  const result = workspaceChangeCodec.safeDecode(source);
  return result.success ? result.data.kind : undefined;
};

const presentationBuildSchema = z.union([
  z.object({
    kind: z.literal("build"),
    phase: z.literal("building"),
  }),
  z.object({
    kind: z.literal("build"),
    build: z.object({}),
    revision: z.string().min(1).nullable(),
  }),
]);
const presentationBuildCodec = jsonCodec(presentationBuildSchema);

export type PresentationBuild =
  | { readonly phase: "building" }
  | { readonly phase: "complete"; readonly revision: string | null };

export const parsePresentationBuild = (source: string): PresentationBuild | undefined => {
  const result = presentationBuildCodec.safeDecode(source);
  if (!result.success) {
    return undefined;
  }
  return "phase" in result.data
    ? { phase: "building" }
    : { phase: "complete", revision: result.data.revision };
};

const presentationChangeSchema = z.object({
  kind: z.literal("presentation"),
  view: viewNameSchema,
  revision: z.string().min(1),
});
const presentationChangeCodec = jsonCodec(presentationChangeSchema);

export const parsePresentationChange = (
  source: string,
): { readonly view: string; readonly revision: string } | undefined => {
  const result = presentationChangeCodec.safeDecode(source);
  return result.success ? { view: result.data.view, revision: result.data.revision } : undefined;
};

const ownerGenerationSchema = z.string().regex(/^[a-f0-9]{64}$/);
const activeViewBaseSchema = z.object({
  schema: z.literal(1),
  generation: z.int().nonnegative(),
  view: viewNameSchema,
});
const activeViewSchema = z.union([
  activeViewBaseSchema.strict(),
  activeViewBaseSchema
    .extend({ catalogGeneration: ownerGenerationSchema, viewGeneration: z.null() })
    .strict(),
  activeViewBaseSchema
    .extend({ catalogGeneration: ownerGenerationSchema, viewGeneration: ownerGenerationSchema })
    .strict(),
]);
const activeViewCodec = jsonCodec(activeViewSchema);

export type ViewActivationOwner =
  | { readonly kind: "absent"; readonly catalogGeneration: string }
  | {
      readonly kind: "present";
      readonly catalogGeneration: string;
      readonly viewGeneration: string;
    };

export interface ActiveViewRequest {
  readonly schema: 1;
  readonly generation: number;
  readonly view: string;
  readonly owner?: ViewActivationOwner;
}

export const parseActiveViewRequest = (source: string): ActiveViewRequest | undefined => {
  const result = activeViewCodec.safeDecode(source);
  if (!result.success) {
    return undefined;
  }
  const request = result.data;
  if (!("catalogGeneration" in request)) {
    return request;
  }
  return {
    schema: request.schema,
    generation: request.generation,
    view: request.view,
    owner:
      request.viewGeneration === null
        ? { kind: "absent", catalogGeneration: request.catalogGeneration }
        : {
            kind: "present",
            catalogGeneration: request.catalogGeneration,
            viewGeneration: request.viewGeneration,
          },
  };
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

const editorDocumentMutationSchema = z.discriminatedUnion("type", [
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-mutation"),
      generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
    })
    .strict(),
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-saved"),
      generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
    })
    .strict(),
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-save-failed"),
      generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
    })
    .strict(),
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-transaction-failed"),
      generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
    })
    .strict(),
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-transaction-applied"),
      generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
      changed: z.boolean(),
    })
    .strict(),
]);

export type EditorDocumentMutation = z.infer<typeof editorDocumentMutationSchema>;

export const parseEditorDocumentMutation = (
  payload: BrowserMessageInput,
): EditorDocumentMutation | undefined => {
  const result = editorDocumentMutationSchema.safeParse(payload);
  return result.success ? result.data : undefined;
};

const editorDocumentMutationAcknowledgementSchema = z.discriminatedUnion("type", [
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-mutation-ready"),
      generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
    })
    .strict(),
  z
    .object({
      schema: z.literal(1),
      type: z.literal("marimo-studio:editor-document-mutation-failed"),
      generation: z.int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    })
    .strict(),
]);

export type EditorDocumentMutationAcknowledgement = z.infer<
  typeof editorDocumentMutationAcknowledgementSchema
>;

export const parseEditorDocumentMutationAcknowledgement = (
  payload: BrowserMessageInput,
): EditorDocumentMutationAcknowledgement | undefined => {
  const result = editorDocumentMutationAcknowledgementSchema.safeParse(payload);
  return result.success ? result.data : undefined;
};

const observeViewSchema = z
  .object({
    schema: z.literal(1),
    requestId: z.string().min(1),
    view: viewNameSchema,
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
