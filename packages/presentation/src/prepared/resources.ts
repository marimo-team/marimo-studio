import type {
  PreparedModelLifecycleNotification as MarimoModelLifecycleNotification,
  PreparedModelResources as MarimoPreparedModelResources,
  PreparedPresentationHandle,
} from "@marimo-studio/marimo-frontend/prepared-presentation";

import { mergeMarimoReplayResources } from "@marimo-team/marimo-export";

import type { DecodedValue } from "../values/codecs.ts";
import type {
  PreparedModelLifecycleNotification,
  PreparedProjectionResources,
  PreparedProjectionSnapshot,
} from "./records.ts";

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
  const resources = mergeMarimoReplayResources([...snapshot.outputs, ...snapshot.cells]);
  return {
    files: resources.files,
    modelNotifications: modelRecords(resources.modelNotifications),
    uiValues: resources.uiValues,
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
