import { z } from "zod";

import {
  FRAME_BRIDGE_MESSAGE_BOUNDS,
  isBoundedBrowserMessage,
  type BrowserMessageInput,
} from "./frame-bridge.ts";
import { runtimeIdSchema } from "./runtime-config";
import { runtimeProgressSchema } from "./runtime-progress.ts";
import { browserDiagnosticSchema, type BrowserDiagnostic } from "./runtime-status";
import { viewNameSchema } from "./views.ts";

const utf8 = new TextEncoder();
const boundedUtf8String = (maximum: number) =>
  z.string().refine((value) => utf8.encode(value).byteLength <= maximum);

const revisionSchema = z.string().min(1).max(256);
const sessionIdSchema = z.string().min(1).max(256);
const querySchema = z.string().max(16_384);
const hashSchema = boundedUtf8String(8_192);
const documentUrlSchema = boundedUtf8String(32 * 1_024).min(1);
const diagnosticTextSchema = boundedUtf8String(64 * 1_024);
const projectionTargetSchema = boundedUtf8String(4_096);

const diagnosticSourceSchema = z.strictObject({
  path: boundedUtf8String(4_096),
  line: z.int().nonnegative(),
  column: z.int().nonnegative(),
});

export const viewDiagnosticSchema = browserDiagnosticSchema.safeExtend({
  code: z.string().min(1).max(128),
  message: diagnosticTextSchema,
  hint: diagnosticTextSchema,
  view: viewNameSchema,
  scope: z.string().min(1).max(128),
  target: projectionTargetSchema.optional(),
  source: diagnosticSourceSchema.optional(),
});

const runtimeField = { runtime: runtimeIdSchema.max(128) };
const documentLifecycleField = {
  lifecycleId: z.int().positive().max(Number.MAX_SAFE_INTEGER),
};

const previewMessageInputSchema = z.discriminatedUnion("type", [
  z.strictObject({
    type: z.literal("marimo-studio:view-progress"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    revision: revisionSchema,
    progress: runtimeProgressSchema.nullable(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:navigate-view"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    query: querySchema,
    hash: hashSchema,
    history: z.literal("push").optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:replay-document"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    url: documentUrlSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:query-change"),
    ...runtimeField,
    ...documentLifecycleField,
    query: querySchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:restore-fragment"),
    ...runtimeField,
    ...documentLifecycleField,
    hash: hashSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:receiver-ready"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema.optional(),
    revision: revisionSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:receiver-unready"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema.optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:receiver-waiting"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema.optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:switch-view"),
    ...runtimeField,
    view: viewNameSchema,
    ...documentLifecycleField,
    documentUrl: documentUrlSchema,
    supportUrl: documentUrlSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:presentation-change"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:presentation-refresh"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    phase: z.enum(["pending", "settled"]),
    diagnostic: viewDiagnosticSchema.optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:presentation-refresh-barrier"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    generation: z.int().positive().max(Number.MAX_SAFE_INTEGER),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:receiver-admitted"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    revision: revisionSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:view-ready"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    revision: revisionSchema,
    sessionId: sessionIdSchema.optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:view-sync-pending"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    diagnostic: viewDiagnosticSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:view-diagnostics"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    diagnostics: z.array(viewDiagnosticSchema).max(200),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:view-error"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    revision: revisionSchema.optional(),
    sessionId: sessionIdSchema.nullable().optional(),
    diagnostic: viewDiagnosticSchema,
  }),
]);

export const previewMessageSchema = previewMessageInputSchema.superRefine((message, context) => {
  let diagnostics: readonly BrowserDiagnostic[] = [];
  if (message.type === "marimo-studio:view-diagnostics") {
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
export type ViewProgressMessage = Extract<PreviewMessage, { type: "marimo-studio:view-progress" }>;
export type NavigateViewMessage = Extract<PreviewMessage, { type: "marimo-studio:navigate-view" }>;
export type ReplayDocumentMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:replay-document" }
>;
export type ViewNavigationIntent = Pick<NavigateViewMessage, "query" | "hash">;
export type QueryChangeMessage = Extract<PreviewMessage, { type: "marimo-studio:query-change" }>;
export type RestoreFragmentMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:restore-fragment" }
>;
export type ReceiverReadyMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-ready" }
>;
export type ReceiverUnreadyMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-unready" }
>;
export type ReceiverWaitingMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-waiting" }
>;
export type SwitchViewMessage = Extract<PreviewMessage, { type: "marimo-studio:switch-view" }>;
export type PresentationChangeMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:presentation-change" }
>;
export type PresentationRefreshMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:presentation-refresh" }
>;
export type PresentationRefreshBarrierMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:presentation-refresh-barrier" }
>;
export type ReceiverAdmittedMessage = Extract<
  PreviewMessage,
  { type: "marimo-studio:receiver-admitted" }
>;
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
export type ViewPreviewMessage =
  | ViewReadyMessage
  | ViewSyncPendingMessage
  | ViewDiagnosticsMessage
  | ViewErrorMessage;
export type PresentationToStudioMessage =
  | ViewProgressMessage
  | NavigateViewMessage
  | QueryChangeMessage
  | ReceiverReadyMessage
  | ReceiverUnreadyMessage
  | ReceiverWaitingMessage
  | ViewPreviewMessage;
export type PresentationToWrapperMessage = ReplayDocumentMessage;
export type StudioToPresentationMessage =
  | SwitchViewMessage
  | RestoreFragmentMessage
  | PresentationChangeMessage
  | PresentationRefreshMessage
  | PresentationRefreshBarrierMessage
  | ReceiverAdmittedMessage;

export const previewMessageFitsBudget = (value: BrowserMessageInput): boolean =>
  isBoundedBrowserMessage(value, FRAME_BRIDGE_MESSAGE_BOUNDS);

export const parsePreviewMessage = (value: BrowserMessageInput): PreviewMessage | undefined => {
  if (!previewMessageFitsBudget(value)) {
    return undefined;
  }
  const result = previewMessageSchema.safeParse(value);
  return result.success ? result.data : undefined;
};
