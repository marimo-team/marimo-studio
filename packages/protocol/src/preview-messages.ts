import { z } from "zod";

import { runtimeIdSchema } from "./runtime-config";

export const viewDiagnosticSchema = z.object({
  code: z.string().optional(),
  severity: z.enum(["warning", "error"]).optional(),
  message: z.string(),
  hint: z.string().optional(),
  view: z.string().optional(),
  scope: z.string().optional(),
  target: z.string().optional(),
  source: z
    .object({
      path: z.string(),
      line: z.int(),
      column: z.int(),
    })
    .optional(),
});

const runtimeField = { runtime: runtimeIdSchema };

const previewMessageInputSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("marimo-studio:navigate-view"),
    ...runtimeField,
    view: z.string(),
  }),
  z.object({
    type: z.literal("marimo-studio:query-change"),
    ...runtimeField,
    query: z.string(),
  }),
  z.object({
    type: z.literal("marimo-studio:receiver-ready"),
    ...runtimeField,
    view: z.string().optional(),
  }),
  z.object({
    type: z.literal("marimo-studio:switch-view"),
    ...runtimeField,
    view: z.string(),
    documentUrl: z.string(),
    supportUrl: z.string(),
  }),
  z.object({
    type: z.literal("marimo-studio:view-ready"),
    ...runtimeField,
    view: z.string(),
    revision: z.string().min(1),
    sessionId: z.string().optional(),
  }),
  z.object({
    type: z.literal("marimo-studio:view-sync-pending"),
    ...runtimeField,
    view: z.string(),
    message: z.string(),
    hint: z.string().optional(),
  }),
  z.object({
    type: z.literal("marimo-studio:view-diagnostics"),
    ...runtimeField,
    view: z.string(),
    diagnostics: z.array(viewDiagnosticSchema),
  }),
  z.object({
    type: z.literal("marimo-studio:view-error"),
    ...runtimeField,
    view: z.string(),
    message: z.string(),
    hint: z.string().optional(),
  }),
  z.object({
    type: z.literal("marimo-studio:view-observation"),
    ...runtimeField,
    view: z.string(),
    revision: z.string().min(1),
    state: z.enum(["ready", "error"]),
    diagnostics: z.array(viewDiagnosticSchema),
  }),
]);

export const previewMessageSchema = previewMessageInputSchema.transform((message) => {
  if (
    message.type === "marimo-studio:view-sync-pending" ||
    message.type === "marimo-studio:view-error"
  ) {
    return { ...message, hint: message.hint ?? message.message };
  }
  return message;
});

export type ViewDiagnostic = z.infer<typeof viewDiagnosticSchema>;
export type PreviewMessage = z.infer<typeof previewMessageSchema>;
export type NavigateViewMessage = Extract<PreviewMessage, { type: "marimo-studio:navigate-view" }>;
export type QueryChangeMessage = Extract<PreviewMessage, { type: "marimo-studio:query-change" }>;
export type ReceiverReadyMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-ready" }
>;
export type SwitchViewMessage = Extract<PreviewMessage, { type: "marimo-studio:switch-view" }>;
export type ViewReadyMessage = Extract<PreviewMessage, { type: "marimo-studio:view-ready" }>;
export type ViewSyncPendingMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:view-sync-pending" }
>;
export type ViewDiagnosticsMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:view-diagnostics" }
>;
export type ViewErrorMessage = Extract<PreviewMessage, { type: "marimo-studio:view-error" }>;
export type ViewObservationMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:view-observation" }
>;
export type ViewPreviewMessage =
  | ViewReadyMessage
  | ViewSyncPendingMessage
  | ViewDiagnosticsMessage
  | ViewErrorMessage
  | ViewObservationMessage;
export type PresentationToStudioMessage =
  | NavigateViewMessage
  | QueryChangeMessage
  | ReceiverReadyMessage
  | ViewPreviewMessage;
export type StudioToPresentationMessage = SwitchViewMessage;

export const parsePreviewMessage = (value: unknown): PreviewMessage | undefined => {
  const result = previewMessageSchema.safeParse(value);
  return result.success ? result.data : undefined;
};
