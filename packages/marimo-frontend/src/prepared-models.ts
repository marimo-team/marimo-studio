import type { ModelLifecycle } from "@marimo-team/frontend/unstable_internal/core/kernel/messages";
import type { Model } from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/model";
import type {
  ModelState,
  WidgetModelId,
} from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/types";

import { getMarimoInternal } from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/model";
import {
  handleWidgetMessage,
  WidgetRegistry,
  WIDGET_REGISTRY,
} from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/registry";
import {
  getInvalidAnyWidgetModuleError,
  resolveAnyWidget,
} from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/resolve-widget";
import {
  decodeFromWire,
  serializeBuffersToBase64,
} from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/serialization";
import { WIDGET_DEF_REGISTRY } from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/widget-binding";

import type {
  PreparedModelGraphCheckpoint,
  PreparedModelGraphPort as ModelGraphPort,
} from "./prepared-model-graph.ts";

import { PreparedModelGraph, PreparedModelGraphReplacementError } from "./prepared-model-graph.ts";

export type PreparedModelLifecycleNotification = ModelLifecycle;

export interface PreparedModelResources {
  readonly files: Readonly<Record<string, string>>;
  readonly modelNotifications: readonly PreparedModelLifecycleNotification[];
}

export interface PreparedModelReplacement {
  readonly mutated: boolean;
  readonly remount: boolean;
  commit(): Promise<void>;
  rollback(): Promise<void>;
}

export interface PreparedModelLifecycleHandle {
  abortSetup(): void;
  activate(): void;
  snapshot(): PreparedModelResources;
  replace(
    resources: PreparedModelResources,
    signal?: AbortSignal,
  ): Promise<PreparedModelReplacement>;
  dispose(): Promise<void>;
}

interface OrderedModelNotification {
  readonly sequence: number;
  readonly notification: PreparedModelLifecycleNotification;
}

interface PreparedModelRecord {
  readonly canonical: string;
  readonly id: WidgetModelId;
  readonly notifications: readonly OrderedModelNotification[];
  readonly active: boolean;
}

interface PreparedModelLiveState {
  readonly model: Model<ModelState>;
  readonly state: ModelState;
}

type PreparedModelGraphPort = ModelGraphPort<PreparedModelRecord, PreparedModelLiveState>;

export const requiresPreparedModelRemount = (cause: unknown): boolean =>
  cause instanceof PreparedModelGraphReplacementError;

interface MarimoStaticState {
  readonly files: Record<string, string>;
}

interface ModelCheckpointState {
  readonly graph: PreparedModelGraphCheckpoint<PreparedModelRecord>;
  readonly sourceResources: PreparedModelResources;
  readonly sourceRecords: ReadonlyMap<string, PreparedModelRecord>;
}

// SAFETY: Marimo's static renderer reads this state from the browser global.
const browser = globalThis as typeof globalThis & {
  __MARIMO_STATIC__?: MarimoStaticState;
};

let activeOwner: object | undefined;

const modelFailure = (cause: unknown): Error =>
  cause instanceof Error ? cause : new Error(String(cause));

const throwIfAborted = (signal: AbortSignal | undefined): void => {
  signal?.throwIfAborted();
};

const widgetModelId = (value: string): WidgetModelId => {
  if (value.length === 0) {
    throw new Error("Prepared model identifiers must not be empty");
  }
  // SAFETY: The non-empty check matches Marimo's WidgetModelId predicate.
  return value as WidgetModelId;
};

const modelRecords = (
  notifications: readonly PreparedModelLifecycleNotification[],
): ReadonlyMap<string, PreparedModelRecord> => {
  const grouped = new Map<string, OrderedModelNotification[]>();
  for (const [sequence, notification] of notifications.entries()) {
    const id = widgetModelId(notification.model_id);
    const current = grouped.get(id) ?? [];
    current.push({ sequence, notification });
    grouped.set(id, current);
  }
  return new Map(
    [...grouped].map(([id, values]) => {
      const notifications = structuredClone(values);
      return [
        id,
        {
          id: widgetModelId(id),
          notifications,
          canonical: JSON.stringify(notifications.map(({ notification }) => notification)),
          active: notifications.at(-1)?.notification.message.method !== "close",
        },
      ];
    }),
  );
};

const replay = async (
  records: readonly PreparedModelRecord[],
  signal?: AbortSignal,
): Promise<void> => {
  const notifications = records
    .flatMap((record) => record.notifications)
    .toSorted((left, right) => left.sequence - right.sequence);
  for (const { notification } of notifications) {
    throwIfAborted(signal);
    await handleWidgetMessage(WIDGET_REGISTRY, structuredClone(notification));
  }
  throwIfAborted(signal);
};

const validateRecord = async (record: PreparedModelRecord, signal?: AbortSignal): Promise<void> => {
  const registry = new WidgetRegistry(1);
  try {
    for (const { notification } of record.notifications) {
      throwIfAborted(signal);
      const method = notification.message.method;
      if (
        method !== "open" &&
        method !== "close" &&
        registry.getModelSync(record.id) === undefined
      ) {
        await handleWidgetMessage(registry, {
          model_id: record.id,
          message: { method: "open", state: {}, buffer_paths: [], buffers: [] },
        });
      }
      await handleWidgetMessage(registry, structuredClone(notification));
    }
  } finally {
    await registry.delete(record.id);
  }
};

const esmSpec = (
  record: PreparedModelRecord,
): { readonly hash: string; readonly url: string } | undefined => {
  for (let index = record.notifications.length - 1; index >= 0; index -= 1) {
    const { notification } = record.notifications[index]!;
    if ("esm_spec" in notification.message && notification.message.esm_spec) {
      return notification.message.esm_spec;
    }
  }
  return undefined;
};

const preflightModule = async (
  record: PreparedModelRecord,
  signal?: AbortSignal,
): Promise<void> => {
  throwIfAborted(signal);
  const spec = esmSpec(record);
  if (spec === undefined) {
    return;
  }
  const module = await WIDGET_DEF_REGISTRY.getModule({
    jsUrl: spec.url,
    jsHash: spec.hash,
    kernelAuthored: true,
  });
  throwIfAborted(signal);
  if (resolveAnyWidget(module, spec.url) !== null) {
    return;
  }
  WIDGET_DEF_REGISTRY.invalidate(spec.hash);
  throw getInvalidAnyWidgetModuleError(module, spec.url);
};

const captureLiveModel = (id: string): PreparedModelLiveState => {
  const modelId = widgetModelId(id);
  const model = WIDGET_REGISTRY.getModelSync(modelId);
  if (model === undefined) {
    throw new Error(`Prepared model ${JSON.stringify(id)} is missing from Marimo's registry`);
  }
  return { model, state: getMarimoInternal(model).snapshotState() };
};

const mergeLiveState = (
  record: PreparedModelRecord,
  live: PreparedModelLiveState,
): PreparedModelRecord => {
  const finalState = record.notifications.findLastIndex(
    ({ notification }) =>
      notification.message.method === "open" || notification.message.method === "update",
  );
  const notifications = record.notifications.map((entry, index) => {
    const { notification } = entry;
    const message = notification.message;
    if (index !== finalState || (message.method !== "open" && message.method !== "update")) {
      return entry;
    }
    const decoded = decodeFromWire({
      state: structuredClone(message.state),
      bufferPaths: message.buffer_paths.map((path) => [...path]),
      buffers: message.buffers,
    });
    const wire = serializeBuffersToBase64({ ...decoded, ...structuredClone(live.state) });
    return {
      sequence: entry.sequence,
      notification: {
        ...notification,
        message: {
          ...message,
          state: wire.state,
          buffer_paths: wire.bufferPaths,
          buffers: wire.buffers,
        },
      },
    };
  });
  return {
    ...record,
    notifications,
    canonical: JSON.stringify(notifications.map(({ notification }) => notification)),
  };
};

const restoreLiveModel = (id: string, live: PreparedModelLiveState): void => {
  if (WIDGET_REGISTRY.getModelSync(widgetModelId(id)) !== live.model) {
    throw new Error(`Prepared model ${JSON.stringify(id)} changed identity during rollback`);
  }
  getMarimoInternal(live.model).updateAndEmitDiffs(structuredClone(live.state));
};

const validateActiveRecord = async (
  record: PreparedModelRecord,
  signal?: AbortSignal,
): Promise<void> => {
  if (!record.notifications.some(({ notification }) => notification.message.method === "open")) {
    throw new Error(
      `Prepared model ${JSON.stringify(record.id)} has no complete open notification`,
    );
  }
  if (record.notifications.some(({ notification }) => notification.message.method === "close")) {
    throw new Error(
      `Prepared model ${JSON.stringify(record.id)} mixes active and closed lifecycle records`,
    );
  }
  await validateRecord(record, signal);
};

const createGraphPort = (): PreparedModelGraphPort => ({
  id: (record) => record.id,
  active: (record) => record.active,
  same: (left, right) => left.canonical === right.canonical,
  changesModule: (previous, next) => esmSpec(previous)?.hash !== esmSpec(next)?.hash,
  capture: captureLiveModel,
  merge: mergeLiveState,
  replay,
  restore: restoreLiveModel,
  close: (id) => WIDGET_REGISTRY.delete(widgetModelId(id)),
  setFiles(files) {
    browser.__MARIMO_STATIC__ = { files: { ...files } };
  },
  validate: validateActiveRecord,
  preflight: preflightModule,
});

export const createPreparedModelLifecycle = (): PreparedModelLifecycleHandle => {
  if (activeOwner) {
    throw new Error("Prepared model lifecycle already has an owner in this page");
  }
  const owner = {};
  activeOwner = owner;
  const previousStatic = browser.__MARIMO_STATIC__;
  const initialFiles = structuredClone(previousStatic?.files ?? {});
  let environmentReleased = false;
  const releaseEnvironment = (): void => {
    if (environmentReleased) {
      return;
    }
    environmentReleased = true;
    if (previousStatic === undefined) {
      delete browser.__MARIMO_STATIC__;
    } else {
      browser.__MARIMO_STATIC__ = previousStatic;
    }
    if (activeOwner === owner) {
      activeOwner = undefined;
    }
  };

  let graph: PreparedModelGraph<PreparedModelRecord, PreparedModelLiveState>;
  try {
    graph = new PreparedModelGraph(createGraphPort(), {
      files: initialFiles,
      records: new Map(),
    });
  } catch (error) {
    releaseEnvironment();
    throw error;
  }

  let activeResources: PreparedModelResources = {
    files: initialFiles,
    modelNotifications: [],
  };
  let activeRecords: ReadonlyMap<string, PreparedModelRecord> = new Map();
  let activated = false;
  let disposed = false;
  let disposal: Promise<void> | undefined;
  const checkpoints = new WeakMap<PreparedModelResources, ModelCheckpointState>();

  const abortSetup = (): void => {
    if (disposed) {
      return;
    }
    if (activated || disposal !== undefined) {
      throw new Error("Prepared model setup is already active");
    }
    disposed = true;
    releaseEnvironment();
  };

  const activate = (): void => {
    if (disposed) {
      throw new Error("Prepared model setup was aborted");
    }
    activated = true;
  };

  const snapshot = (): PreparedModelResources => {
    if (disposed) {
      throw new Error("Prepared models are disposed");
    }
    const modelNotifications: PreparedModelLifecycleNotification[] = structuredClone([
      ...activeResources.modelNotifications,
    ]);
    for (const record of activeRecords.values()) {
      if (!record.active) {
        continue;
      }
      const wire = serializeBuffersToBase64(captureLiveModel(record.id).state);
      modelNotifications.push({
        model_id: record.id,
        message: {
          method: "update",
          state: wire.state,
          buffer_paths: wire.bufferPaths,
          buffers: wire.buffers,
        },
      });
    }
    const resources = {
      files: structuredClone(activeResources.files),
      modelNotifications,
    };
    checkpoints.set(resources, {
      graph: graph.checkpoint(),
      sourceResources: activeResources,
      sourceRecords: activeRecords,
    });
    return resources;
  };

  const replace = async (
    resources: PreparedModelResources,
    signal?: AbortSignal,
  ): Promise<PreparedModelReplacement> => {
    if (disposed) {
      return Object.freeze({
        mutated: false,
        remount: false,
        commit: async () => undefined,
        rollback: async () => {},
      });
    }
    activate();
    const checkpoint = checkpoints.get(resources);
    const next: PreparedModelResources = structuredClone(resources);
    const nextRecords = modelRecords(next.modelNotifications);
    const target = checkpoint?.graph ?? {
      files: next.files,
      records: nextRecords,
    };
    const replacement = await graph.replace(target, signal);
    return Object.freeze({
      mutated: replacement.mutated,
      remount: replacement.remount,
      async commit() {
        const adopted = await replacement.commit();
        if (adopted !== undefined) {
          activeResources = checkpoint?.sourceResources ?? next;
          activeRecords = checkpoint?.sourceRecords ?? adopted.records;
        }
      },
      rollback: () => replacement.rollback(),
    });
  };

  const dispose = (): Promise<void> => {
    if (!activated) {
      abortSetup();
      return Promise.resolve();
    }
    disposal ??= (async () => {
      disposed = true;
      const errors: Error[] = [];
      try {
        await graph.dispose();
      } catch (error) {
        errors.push(modelFailure(error));
      }
      try {
        releaseEnvironment();
      } catch (error) {
        errors.push(modelFailure(error));
      }
      if (errors.length === 1) {
        throw errors[0];
      }
      if (errors.length > 1) {
        throw new AggregateError(errors, "Prepared model disposal failed");
      }
    })();
    return disposal;
  };

  return Object.freeze({ abortSetup, activate, snapshot, replace, dispose });
};
