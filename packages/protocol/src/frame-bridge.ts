import { z } from "zod";

import { jsonValueSchema } from "./runtime-config.ts";
import { viewNameSchema } from "./views.ts";

const requestIdSchema = z.string().regex(/^[A-Za-z0-9_-]{1,128}$/);
const generationSchema = z.string().regex(/^[A-Za-z0-9_-]{8,128}$/);
const frameIdentityFields = {
  lifecycleId: z.int().positive(),
  revision: z.string().min(1).max(256),
  runtime: z.string().min(1).max(128),
  sessionId: z.string().min(1).max(256).nullable(),
  view: viewNameSchema,
};

export const frameControlUpdateSchema = z.strictObject({
  objectId: z.string().min(1).max(512),
  value: jsonValueSchema,
  origin: z.enum(["input", "registration"]).optional(),
});

export type FrameControlUpdate = z.infer<typeof frameControlUpdateSchema>;

const controlPathStepSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("element") }),
  z.strictObject({ kind: z.literal("index"), value: z.int().nonnegative() }),
  z.strictObject({ kind: z.literal("key"), value: z.string().max(512) }),
]);

export const controlMetadataSchema = z.strictObject({
  cells: z.record(z.string().max(512), z.string().max(512)),
  bindings: z
    .record(
      z.string().max(512),
      z.strictObject({
        input: z.string().min(1).max(512),
        path: z.array(controlPathStepSchema).max(64),
      }),
    )
    .optional(),
});

export type ControlMetadata = z.infer<typeof controlMetadataSchema>;
export type ControlBindings = NonNullable<ControlMetadata["bindings"]>;

export const editorControlsSchema = z.strictObject({
  schema: z.literal(1),
  revision: z.string().min(1).max(256),
  controls: controlMetadataSchema,
});

export const frameControlUpdatesSchema = z.array(frameControlUpdateSchema).max(1_024);

export const frameBridgeMessageSchema = z.discriminatedUnion("type", [
  z.strictObject({
    type: z.literal("marimo-studio:frame-bridge-ready"),
    ...frameIdentityFields,
    generation: generationSchema,
    controls: z.array(frameControlUpdateSchema).max(1_024),
    controlMetadata: controlMetadataSchema.nullable().optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:frame-control-update"),
    ...frameIdentityFields,
    generation: generationSchema,
    update: frameControlUpdateSchema,
  }),
  z.strictObject({
    type: z.literal("marimo-studio:frame-control-apply"),
    ...frameIdentityFields,
    generation: generationSchema,
    requestId: requestIdSchema,
    updates: z.array(frameControlUpdateSchema).max(1_024),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:frame-control-applied"),
    ...frameIdentityFields,
    generation: generationSchema,
    requestId: requestIdSchema,
    error: z.string().max(1_024).optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:frame-query-apply"),
    ...frameIdentityFields,
    generation: generationSchema,
    requestId: requestIdSchema,
    query: z.string().max(16_384),
    hash: z.string().max(8_192).optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:frame-query-applied"),
    ...frameIdentityFields,
    generation: generationSchema,
    requestId: requestIdSchema,
    error: z.string().max(1_024).optional(),
  }),
  z.strictObject({
    type: z.literal("marimo-studio:frame-resize"),
    ...frameIdentityFields,
    generation: generationSchema,
  }),
]);

export type FrameBridgeMessage = z.infer<typeof frameBridgeMessageSchema>;

export interface BrowserMessageBounds {
  maxDepth: number;
  maxNodes: number;
  maxTextBytes: number;
}

const browserMessageInputSchema = z.unknown();
const browserMessageTextSchema = z.string();
const browserMessageScalarSchema = z.union([z.null(), z.boolean(), z.number().finite()]);
const browserMessageObjectSchema = z.custom<object>((value) => {
  try {
    const prototype = Object.getPrototypeOf(value);
    return prototype === null || Object.getPrototypeOf(prototype) === null;
  } catch {
    return false;
  }
});

export type BrowserMessageInput = z.input<typeof browserMessageInputSchema>;

export const FRAME_BRIDGE_MESSAGE_BOUNDS: BrowserMessageBounds = {
  maxDepth: 32,
  maxNodes: 10_000,
  maxTextBytes: 256 * 1_024,
};

export const isBoundedBrowserMessage = (
  value: BrowserMessageInput,
  bounds: BrowserMessageBounds = FRAME_BRIDGE_MESSAGE_BOUNDS,
): boolean => {
  const pending: Array<{ depth: number; value: BrowserMessageInput }> = [{ depth: 0, value }];
  const seen = new WeakSet<object>();
  let nodes = 0;
  let textBytes = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (!current || current.depth > bounds.maxDepth || ++nodes > bounds.maxNodes) {
      return false;
    }
    const text = browserMessageTextSchema.safeParse(current.value);
    if (text.success) {
      textBytes += new TextEncoder().encode(text.data).byteLength;
      if (textBytes > bounds.maxTextBytes) {
        return false;
      }
      continue;
    }
    if (browserMessageScalarSchema.safeParse(current.value).success) {
      continue;
    }
    if (Array.isArray(current.value)) {
      if (seen.has(current.value)) {
        return false;
      }
      seen.add(current.value);
      current.value.forEach((item) => pending.push({ depth: current.depth + 1, value: item }));
      continue;
    }
    const messageObject = browserMessageObjectSchema.safeParse(current.value);
    if (!messageObject.success || seen.has(messageObject.data)) {
      return false;
    }
    seen.add(messageObject.data);
    Object.entries(messageObject.data).forEach(([key, item]) => {
      pending.push({ depth: current.depth + 1, value: key });
      pending.push({ depth: current.depth + 1, value: item });
    });
  }
  return true;
};

export const parseFrameBridgeMessage = (
  value: BrowserMessageInput,
): FrameBridgeMessage | undefined => {
  if (!isBoundedBrowserMessage(value)) {
    return undefined;
  }
  const parsed = frameBridgeMessageSchema.safeParse(value);
  return parsed.success ? parsed.data : undefined;
};
