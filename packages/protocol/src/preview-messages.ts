import { z } from "zod";

import { browserDiagnosticSchema, type BrowserDiagnostic } from "./browser-observations";
import { shellChangeKindSchema } from "./development-events";
import { runtimeIdSchema, type JsonValue } from "./runtime-config";

export const viewDiagnosticSchema = browserDiagnosticSchema;

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
    type: z.literal("marimo-studio:receiver-unready"),
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
    type: z.literal("marimo-studio:source-change"),
    ...runtimeField,
    view: z.string(),
    kind: shellChangeKindSchema,
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
    diagnostic: browserDiagnosticSchema,
  }),
  z.object({
    type: z.literal("marimo-studio:view-diagnostics"),
    ...runtimeField,
    view: z.string(),
    diagnostics: z.array(viewDiagnosticSchema).max(200),
  }),
  z.object({
    type: z.literal("marimo-studio:view-error"),
    ...runtimeField,
    view: z.string(),
    diagnostic: browserDiagnosticSchema,
  }),
  z
    .object({
      type: z.literal("marimo-studio:view-observation"),
      ...runtimeField,
      view: z.string(),
      revision: z.string().min(1),
      state: z.enum(["ready", "loading", "error"]),
      diagnostics: z.array(browserDiagnosticSchema).max(200),
      runtimeInstance: z.string().min(1),
      sessionId: z.string().min(1).nullable(),
      requestId: z.string().min(1),
      query: z.string(),
    })
    .strict(),
  z
    .object({
      type: z.literal("marimo-studio:observe-view"),
      ...runtimeField,
      view: z.string().min(1),
      revision: z.string().min(1),
      runtimeInstance: z.string().min(1),
      requestId: z.string().min(1),
    })
    .strict(),
]);

export const previewMessageSchema = previewMessageInputSchema.superRefine((message, context) => {
  let diagnostics: readonly BrowserDiagnostic[] = [];
  if (
    message.type === "marimo-studio:view-diagnostics" ||
    message.type === "marimo-studio:view-observation"
  ) {
    diagnostics = message.diagnostics;
  } else if (
    message.type === "marimo-studio:view-sync-pending" ||
    message.type === "marimo-studio:view-error"
  ) {
    diagnostics = [message.diagnostic];
  }
  if ("view" in message && diagnostics.some((diagnostic) => diagnostic.view !== message.view)) {
    context.addIssue({
      code: "custom",
      message: "Preview diagnostics must target the message view",
      path: ["view"],
    });
  }
});

export type ViewDiagnostic = BrowserDiagnostic;
export type PreviewMessage = z.infer<typeof previewMessageSchema>;
export type NavigateViewMessage = Extract<PreviewMessage, { type: "marimo-studio:navigate-view" }>;
export type QueryChangeMessage = Extract<PreviewMessage, { type: "marimo-studio:query-change" }>;
export type ReceiverReadyMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-ready" }
>;
export type ReceiverUnreadyMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-unready" }
>;
export type SwitchViewMessage = Extract<PreviewMessage, { type: "marimo-studio:switch-view" }>;
export type SourceChangeMessage = Extract<PreviewMessage, { type: "marimo-studio:source-change" }>;
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
export type ObserveViewMessage = Extract<PreviewMessage, { type: "marimo-studio:observe-view" }>;
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
  | ReceiverUnreadyMessage
  | ViewPreviewMessage;
export type StudioToPresentationMessage =
  | SwitchViewMessage
  | SourceChangeMessage
  | ObserveViewMessage;

export const parsePreviewMessage = (value: JsonValue): PreviewMessage | undefined => {
  const result = previewMessageSchema.safeParse(value);
  return result.success ? result.data : undefined;
};
