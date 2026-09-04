import type {
  PreparedModelLifecycleNotification as MarimoModelLifecycleNotification,
  PreparedModelResources as MarimoPreparedModelResources,
  PreparedPresentationHandle,
} from "@marimo-studio/marimo-frontend/prepared-presentation";

import { jsonValueSchema, type JsonValue } from "@marimo-studio/protocol/runtime-config";

import type { DecodedValue } from "../values/codecs.ts";
import type {
  PreparedModelLifecycleNotification,
  PreparedProjectionResources,
  PreparedProjectionSnapshot,
} from "./records.ts";

import { PreparedProjectionCapabilityError } from "./errors.ts";

export type PreparedOutputOwners = ReadonlyMap<string, readonly string[]>;

export const preparedOutputOwners = (
  snapshot: PreparedProjectionSnapshot,
): Map<string, readonly string[]> => {
  const owners = new Map<string, readonly string[]>();
  const add = (owner: string, resources: PreparedProjectionResources): void => {
    const ids = Object.keys(resources.functions);
    const current = owners.get(owner) ?? [];
    owners.set(owner, [...new Set([...current, ...ids])]);
  };
  snapshot.outputs.forEach((output) => add(output.ownerCellId, output.resources));
  snapshot.cells.forEach((cell) => add(cell.cell.id, cell.resources));
  return owners;
};

const resourceRecords = (
  snapshot: PreparedProjectionSnapshot,
): readonly {
  readonly ownerCellId: string;
  readonly projectionSha256: string;
  readonly resources: PreparedProjectionResources;
}[] => [
  ...snapshot.outputs.map((output) => ({
    ownerCellId: output.ownerCellId,
    projectionSha256: output.projectionSha256,
    resources: output.resources,
  })),
  ...snapshot.cells.map((cell) => ({
    ownerCellId: cell.cell.id,
    projectionSha256: cell.projectionSha256,
    resources: cell.resources,
  })),
];

const projectionDigest = (value: string): string => {
  if (!/^[0-9a-f]{64}$/u.test(value)) {
    throw new Error(`Prepared projection digest ${JSON.stringify(value)} is invalid.`);
  }
  return value;
};

const validatePreparedUiResources = (
  ownerCellId: string,
  projectionSha256: string,
  resources: PreparedProjectionResources,
): void => {
  const digest = projectionDigest(projectionSha256);
  const uiPrefix = `${ownerCellId}-projection-${digest}-ui-`;
  const modelPrefix = `projection-${digest}-model-`;
  const functionIds = Object.keys(resources.functions);
  for (const [objectId, names] of Object.entries(resources.functions)) {
    if (names.length > 0) {
      throw new PreparedProjectionCapabilityError(
        "prepared-functions-unsupported",
        `Prepared UI object ${JSON.stringify(objectId)} requires Python functions: ${names.join(", ")}.`,
      );
    }
  }
  const uiValueIds = Object.keys(resources.uiValues);
  const allIds = new Set([...functionIds, ...uiValueIds]);
  for (const objectId of allIds) {
    if (!objectId.startsWith(uiPrefix) || objectId.length === uiPrefix.length) {
      throw new Error(
        `Prepared UI object ${JSON.stringify(objectId)} is outside projection owner ${JSON.stringify(ownerCellId)}.`,
      );
    }
  }
  for (const notification of resources.modelNotifications) {
    if (
      !notification.model_id.startsWith(modelPrefix) ||
      notification.model_id.length === modelPrefix.length
    ) {
      throw new Error(
        `Prepared model ${JSON.stringify(notification.model_id)} is outside projection ${JSON.stringify(digest)}.`,
      );
    }
  }
  if (
    functionIds.length !== uiValueIds.length ||
    functionIds.some((objectId) => !Object.hasOwn(resources.uiValues, objectId))
  ) {
    throw new Error(
      `Prepared projection owner ${JSON.stringify(ownerCellId)} has mismatched function and UI value resources.`,
    );
  }
};

type MarimoModelBuffer = Extract<
  MarimoModelLifecycleNotification["message"],
  { buffers: unknown }
>["buffers"][number];

const marimoModelBuffers = (buffers: readonly string[]): MarimoModelBuffer[] =>
  buffers.map((buffer) => {
    // SAFETY: Marimo defines lifecycle buffers as base64 strings, and this adapter preserves the serialized wire value.
    return buffer as MarimoModelBuffer;
  });

const marimoModelMessage = (
  message: PreparedModelLifecycleNotification["message"],
): MarimoModelLifecycleNotification["message"] => {
  if (message.method === "open" || message.method === "update") {
    return {
      method: message.method,
      state: structuredClone(message.state),
      buffer_paths: message.buffer_paths.map((path) => [...path]),
      buffers: marimoModelBuffers(message.buffers),
      esm_spec: message.esm_spec === null ? null : { ...message.esm_spec },
    };
  }
  if (message.method === "custom") {
    return {
      method: message.method,
      content: structuredClone(message.content),
      buffers: marimoModelBuffers(message.buffers),
    };
  }
  return { method: message.method };
};

const modelRecords = (
  values: readonly PreparedModelLifecycleNotification[],
): readonly MarimoModelLifecycleNotification[] =>
  values.map(({ message, model_id }) => ({
    message: marimoModelMessage(message),
    model_id,
  }));

type PreparedUiValues = Parameters<PreparedPresentationHandle["uiValues"]["stage"]>[0];

export type PreparedResources = Omit<ReturnType<typeof prepareProjectionResources>, "uiValues"> & {
  readonly uiValues: PreparedUiValues;
  readonly modelCheckpoint?: MarimoPreparedModelResources;
};

export const prepareProjectionResources = (snapshot: PreparedProjectionSnapshot) => {
  const files = new Map<string, string>();
  const uiValues = new Map<string, { readonly canonical: string; readonly value: JsonValue }>();
  const modelNotifications = new Map<
    string,
    { readonly canonical: string; readonly notification: PreparedModelLifecycleNotification }
  >();
  for (const { ownerCellId, projectionSha256, resources } of resourceRecords(snapshot)) {
    validatePreparedUiResources(ownerCellId, projectionSha256, resources);
    for (const [name, dataUrl] of Object.entries(resources.files)) {
      const existing = files.get(name);
      if (existing !== undefined && existing !== dataUrl) {
        throw new Error(`Prepared resource file ${JSON.stringify(name)} has conflicting contents.`);
      }
      files.set(name, dataUrl);
    }
    for (const notification of resources.modelNotifications) {
      const canonical = JSON.stringify(notification);
      const existing = modelNotifications.get(notification.model_id);
      if (existing !== undefined && existing.canonical !== canonical) {
        throw new Error(
          `Prepared model ${JSON.stringify(notification.model_id)} has conflicting lifecycle records.`,
        );
      }
      modelNotifications.set(notification.model_id, { canonical, notification });
    }
    for (const [objectId, value] of Object.entries(resources.uiValues)) {
      const parsed = jsonValueSchema.parse(value);
      const canonical = JSON.stringify(parsed);
      const existing = uiValues.get(objectId);
      if (existing !== undefined && existing.canonical !== canonical) {
        throw new Error(
          `Prepared UI object ${JSON.stringify(objectId)} has conflicting UI values.`,
        );
      }
      uiValues.set(objectId, { canonical, value: parsed });
    }
  }
  return {
    files: Object.fromEntries(files),
    modelNotifications: modelRecords(
      [...modelNotifications.values()].map(({ notification }) => notification),
    ),
    // SAFETY: jsonValueSchema validates a subset of EmbeddedJsonValue.
    uiValues: Object.fromEntries(
      [...uiValues.entries()].map(([objectId, { value }]) => [objectId, value]),
    ) as PreparedUiValues,
  };
};

export const modelResources = ({
  files,
  modelNotifications,
  modelCheckpoint,
}: PreparedResources): MarimoPreparedModelResources =>
  modelCheckpoint ?? { files, modelNotifications };

export const preparedValueRecord = (
  snapshot: PreparedProjectionSnapshot,
): Record<string, DecodedValue> =>
  Object.fromEntries(snapshot.values.map(({ selector, value }) => [selector, value]));
