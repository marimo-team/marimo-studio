import { z } from "zod";

import { browserDiagnosticSchema, type BrowserDiagnostic } from "./browser-observations";
import {
  FRAME_BRIDGE_MESSAGE_BOUNDS,
  isBoundedBrowserMessage,
  type BrowserMessageInput,
} from "./frame-bridge.ts";
import {
  MAX_ACTIVE_PROJECTION_INSTANCES,
  observedProjectionInstanceSchema,
  projectionInstanceIsReady,
} from "./projections";
import { runtimeIdSchema } from "./runtime-config";
import { viewNameSchema } from "./views.ts";

const OBSERVATION_MESSAGE_BOUNDS = {
  maxDepth: 32,
  maxNodes: 50_000,
  maxTextBytes: 4 * 1_024 * 1_024,
};

const utf8 = new TextEncoder();
const boundedUtf8String = (maximum: number) =>
  z.string().refine((value) => utf8.encode(value).byteLength <= maximum);

const revisionSchema = z.string().min(1).max(256);
const sessionIdSchema = z.string().min(1).max(256);
const requestIdSchema = z.string().min(1).max(256);
const runtimeInstanceSchema = z.string().min(1).max(256);
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

const projectionInstanceSchema = observedProjectionInstanceSchema.safeExtend({
  mountId: z.string().min(1).max(128).nullable(),
  instanceId: z.string().min(1).max(256),
  target: projectionTargetSchema,
  runtimeCellId: z.string().min(1).max(256).nullable(),
  error: z
    .strictObject({
      code: z.string().min(1).max(128),
      message: diagnosticTextSchema,
    })
    .nullable(),
});

const runtimeField = { runtime: runtimeIdSchema.max(128) };
const documentLifecycleField = {
  lifecycleId: z.int().positive().max(Number.MAX_SAFE_INTEGER),
};

const previewMessageInputSchema = z.discriminatedUnion("type", [
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
  z.strictObject({
    type: z.literal("marimo-studio:view-observation"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    revision: revisionSchema,
    state: z.enum(["ready", "loading", "error"]),
    diagnostics: z.array(viewDiagnosticSchema).max(200),
    runtimeInstance: runtimeInstanceSchema,
    sessionId: sessionIdSchema.nullable(),
    requestId: requestIdSchema,
    query: querySchema,
    projectionInstances: z.array(projectionInstanceSchema).max(MAX_ACTIVE_PROJECTION_INSTANCES + 1),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:observe-view"),
    ...runtimeField,
    ...documentLifecycleField,
    view: viewNameSchema,
    revision: revisionSchema,
    runtimeInstance: runtimeInstanceSchema,
    requestId: requestIdSchema,
  }),
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
  if (message.type === "marimo-studio:view-observation") {
    const instanceIds = message.projectionInstances.map((instance) => instance.instanceId);
    if (new Set(instanceIds).size !== instanceIds.length) {
      context.addIssue({
        code: "custom",
        message: "Projection observation evidence is internally inconsistent",
        path: ["projectionInstances"],
      });
    }
    if (
      message.state === "ready" &&
      !message.projectionInstances.every(projectionInstanceIsReady)
    ) {
      context.addIssue({
        code: "custom",
        message: "Ready view observations require every projection instance to be ready",
        path: ["projectionInstances"],
      });
    }
  }
});

export type ViewDiagnostic = BrowserDiagnostic;
export type PreviewMessage = z.infer<typeof previewMessageSchema>;
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
export type PresentationToWrapperMessage = ReplayDocumentMessage;
export type StudioToPresentationMessage =
  | SwitchViewMessage
  | RestoreFragmentMessage
  | PresentationChangeMessage
  | PresentationRefreshMessage
  | PresentationRefreshBarrierMessage
  | ReceiverAdmittedMessage
  | ObserveViewMessage;

const previewMessageDiscriminantSchema = z.object({
  type: z.string().max(64),
});

export const previewMessageFitsBudget = (value: BrowserMessageInput): boolean => {
  if (isBoundedBrowserMessage(value, FRAME_BRIDGE_MESSAGE_BOUNDS)) {
    return true;
  }
  if (!isBoundedBrowserMessage(value, OBSERVATION_MESSAGE_BOUNDS)) {
    return false;
  }
  const discriminant = previewMessageDiscriminantSchema.safeParse(value);
  return discriminant.success && discriminant.data.type === "marimo-studio:view-observation";
};

export const parsePreviewMessage = (value: BrowserMessageInput): PreviewMessage | undefined => {
  if (!previewMessageFitsBudget(value)) {
    return undefined;
  }
  const result = previewMessageSchema.safeParse(value);
  return result.success ? result.data : undefined;
};
