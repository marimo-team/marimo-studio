import type {
  JsonObject,
  MarimoCellChannel,
  MarimoCellOutput,
  MarimoCellSnapshot,
  MarimoEsmSpec,
  MarimoModelLifecycleMessage,
  MarimoModelLifecycleNotification,
  MarimoOutputSnapshot,
  MarimoReplayResources,
} from "@marimo-team/marimo-export";

import type { DecodedValue } from "../values/codecs.ts";

export type PreparedJsonPrimitive = string | number | boolean | null;
export type PreparedJsonValue = Extract<DecodedValue, { readonly codec: "json-v1" }>["value"];
export type PreparedJsonObject = JsonObject;
export type PreparedOutputChannel = MarimoCellChannel;
export type PreparedCellOutput = MarimoCellOutput;
export type PreparedEsmSpec = MarimoEsmSpec;
export type PreparedModelMessage = MarimoModelLifecycleMessage;
export type PreparedModelLifecycleNotification = MarimoModelLifecycleNotification;
export type PreparedProjectionResources = MarimoReplayResources;

export interface PreparedValueSnapshot {
  readonly selector: string;
  readonly value: DecodedValue;
}

export type PreparedOutputSnapshot = MarimoOutputSnapshot & {
  readonly selector: string;
};

export type PreparedCellSnapshot = MarimoCellSnapshot & {
  readonly alias: string;
};

export interface PreparedProjectionSnapshot {
  readonly values: readonly PreparedValueSnapshot[];
  readonly outputs: readonly PreparedOutputSnapshot[];
  readonly cells: readonly PreparedCellSnapshot[];
}

const freezeResources = (resources: MarimoReplayResources): void => {
  Object.values(resources.functions).forEach(Object.freeze);
  resources.modelNotifications.forEach((notification) => {
    Object.freeze(notification.message);
    Object.freeze(notification);
  });
  Object.freeze(resources.files);
  Object.freeze(resources.functions);
  Object.freeze(resources.modelNotifications);
  Object.freeze(resources.uiValues);
  Object.freeze(resources);
};

const requireUnique = (values: readonly string[], label: string): void => {
  if (values.length !== new Set(values).size) {
    throw new Error(`Prepared projection ${label} must be unique`);
  }
};

export const immutablePreparedSnapshot = (
  value: PreparedProjectionSnapshot,
): PreparedProjectionSnapshot => {
  const snapshot: PreparedProjectionSnapshot = {
    values: value.values.map(({ selector, value: decoded }) => ({
      selector,
      value:
        decoded.codec === "json-v1"
          ? { ...decoded, value: structuredClone(decoded.value) }
          : decoded,
    })),
    outputs: structuredClone(value.outputs),
    cells: structuredClone(value.cells),
  };
  requireUnique(
    snapshot.values.map((item) => item.selector),
    "value selectors",
  );
  requireUnique(
    snapshot.outputs.map((item) => item.selector),
    "output selectors",
  );
  requireUnique(
    snapshot.cells.map((item) => item.alias),
    "cell aliases",
  );
  snapshot.values.forEach(Object.freeze);
  snapshot.outputs.forEach((output) => {
    if (output.output !== null) {
      Object.freeze(output.output);
    }
    freezeResources(output.resources);
    Object.freeze(output);
  });
  snapshot.cells.forEach((cell) => {
    cell.console.forEach(Object.freeze);
    if (cell.output !== null) {
      Object.freeze(cell.output);
    }
    Object.freeze(cell.cell.config);
    Object.freeze(cell.cell);
    Object.freeze(cell.console);
    freezeResources(cell.resources);
    Object.freeze(cell);
  });
  Object.freeze(snapshot.values);
  Object.freeze(snapshot.outputs);
  Object.freeze(snapshot.cells);
  Object.freeze(snapshot);
  return snapshot;
};
