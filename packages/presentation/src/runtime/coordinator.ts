import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeRegistry, RuntimeSession } from "@marimo-studio/runtime";

import { commitRuntimeInstance as commitConfiguredRuntimeInstance } from "../runtime-config/store.ts";

let session: RuntimeSession | undefined;
let mountGeneration = 0;
let mounting: { controller: AbortController; generation: number } | undefined;
let runtimeLifecycle: Promise<void> = Promise.resolve();
const runtimeOperations = new Set<AbortController>();
const queryOperations = new Set<AbortController>();

interface RuntimeOperationHandle {
  readonly signal: AbortSignal;
  dispose(): void;
}

export type RuntimeUpdate = "applied" | "pending" | "reload";

export class RuntimeMountCancelledError extends Error {
  constructor() {
    super("Runtime mount was cancelled");
    this.name = "RuntimeMountCancelledError";
  }
}

const enqueueRuntimeLifecycle = <Result>(operation: () => Promise<Result>): Promise<Result> => {
  const result = runtimeLifecycle.then(operation, operation);
  runtimeLifecycle = result.then(
    () => {},
    () => {},
  );
  return result;
};

const abortOperations = (operations: ReadonlySet<AbortController>, reason: DOMException): void => {
  operations.forEach((controller) => controller.abort(reason));
};

const runtimeOperation = (parentSignal: AbortSignal, query: boolean): RuntimeOperationHandle => {
  const controller = new AbortController();
  const abort = () => controller.abort(parentSignal.reason);
  parentSignal.addEventListener("abort", abort, { once: true });
  if (parentSignal.aborted) {
    abort();
  }
  runtimeOperations.add(controller);
  if (query) {
    queryOperations.add(controller);
  }
  return {
    signal: controller.signal,
    dispose() {
      parentSignal.removeEventListener("abort", abort);
      runtimeOperations.delete(controller);
      queryOperations.delete(controller);
    },
  };
};

export interface ConfiguredRuntimeRevision {
  apply(config: RuntimeConfig): Promise<RuntimeUpdate>;
  commit(): Promise<void>;
  rollback(): Promise<void>;
}

export const beginConfiguredRuntimeRevision = async (
  signal: AbortSignal,
): Promise<ConfiguredRuntimeRevision> => {
  abortOperations(
    runtimeOperations,
    new DOMException("Presentation document superseded active runtime operations", "AbortError"),
  );
  const current = session;
  const generation = mountGeneration;
  let acquire = () => {};
  let release = () => {};
  const acquired = new Promise<void>((resolve) => {
    acquire = resolve;
  });
  const released = new Promise<void>((resolve) => {
    release = resolve;
  });
  const held = enqueueRuntimeLifecycle(async () => {
    acquire();
    await released;
  });
  await acquired;
  try {
    signal.throwIfAborted();
    const revision = await current?.beginRevision(signal);
    let settled = false;
    const finish = async (result: "commit" | "rollback") => {
      if (settled) {
        return;
      }
      settled = true;
      try {
        await revision?.[result]();
      } finally {
        release();
        await held;
      }
    };
    return {
      async apply(config) {
        signal.throwIfAborted();
        if (!current || session !== current || generation !== mountGeneration) {
          return "pending";
        }
        const result = await revision?.apply(config);
        signal.throwIfAborted();
        return result ?? "pending";
      },
      commit: async () => await finish("commit"),
      rollback: async () => await finish("rollback"),
    };
  } catch (error) {
    release();
    await held;
    throw error;
  }
};

export const mountConfiguredRuntime = (
  registry: RuntimeRegistry,
  config: RuntimeConfig,
  root: HTMLElement,
): Promise<RuntimeSession> => {
  abortOperations(
    runtimeOperations,
    new DOMException("Presentation runtime mount superseded active operations", "AbortError"),
  );
  const generation = ++mountGeneration;
  mounting?.controller.abort(new RuntimeMountCancelledError());
  const controller = new AbortController();
  mounting = { controller, generation };
  const previous = session;
  session = undefined;
  return enqueueRuntimeLifecycle(async () => {
    try {
      await previous?.dispose();
      if (generation !== mountGeneration) {
        throw new RuntimeMountCancelledError();
      }
      const runtime = registry.resolve(config.runtime.descriptor);
      let mounted: RuntimeSession | undefined;
      let pendingInstance: string | undefined;
      const commitRuntimeInstance = (instance: string): void => {
        if (generation !== mountGeneration || controller.signal.aborted) {
          return;
        }
        if (mounted === undefined || session !== mounted) {
          pendingInstance = instance;
          return;
        }
        commitConfiguredRuntimeInstance(instance);
      };
      try {
        mounted = await runtime.mount(
          { presentation: config, root, signal: controller.signal, commitRuntimeInstance },
          config.runtime.data,
        );
      } catch (error) {
        if (controller.signal.aborted) {
          throw new RuntimeMountCancelledError();
        }
        throw error;
      }
      if (generation !== mountGeneration || controller.signal.aborted) {
        await mounted.dispose();
        throw new RuntimeMountCancelledError();
      }
      session = mounted;
      if (pendingInstance !== undefined) {
        commitConfiguredRuntimeInstance(pendingInstance);
      }
      return mounted;
    } finally {
      if (mounting?.generation === generation) {
        mounting = undefined;
      }
    }
  });
};

export const updateConfiguredRuntime = (
  config: RuntimeConfig,
  signal: AbortSignal = new AbortController().signal,
): Promise<RuntimeUpdate> => {
  const current = session;
  const generation = mountGeneration;
  if (!current) {
    return Promise.resolve("pending");
  }
  abortOperations(
    queryOperations,
    new DOMException("Presentation runtime config superseded active queries", "AbortError"),
  );
  const operation = runtimeOperation(signal, false);
  return enqueueRuntimeLifecycle(async () => {
    let revision: Awaited<ReturnType<RuntimeSession["beginRevision"]>> | undefined;
    try {
      operation.signal.throwIfAborted();
      if (session !== current || generation !== mountGeneration) {
        return "pending";
      }
      revision = await current.beginRevision(operation.signal);
      const result = await revision.apply(config);
      operation.signal.throwIfAborted();
      await revision.commit();
      return result;
    } catch (error) {
      if (revision === undefined) {
        throw error;
      }
      try {
        await revision.rollback();
      } catch (rollbackError) {
        throw new AggregateError([error, rollbackError], "Runtime update and rollback failed.");
      }
      throw error;
    } finally {
      operation.dispose();
    }
  });
};

export const updateConfiguredRuntimeQuery = (
  query: string,
  signal: AbortSignal = new AbortController().signal,
): Promise<void> => {
  const current = session;
  const generation = mountGeneration;
  if (!current) {
    return Promise.reject(new Error("The presentation runtime is still starting"));
  }
  abortOperations(
    queryOperations,
    new DOMException("Presentation runtime query superseded", "AbortError"),
  );
  const operation = runtimeOperation(signal, true);
  return enqueueRuntimeLifecycle(async () => {
    try {
      operation.signal.throwIfAborted();
      if (session !== current || generation !== mountGeneration) {
        return;
      }
      await current.updateQuery?.(query, operation.signal);
      operation.signal.throwIfAborted();
    } finally {
      operation.dispose();
    }
  });
};

export const disposeConfiguredRuntime = (): Promise<void> => {
  abortOperations(
    runtimeOperations,
    new DOMException("Presentation runtime disposed", "AbortError"),
  );
  mountGeneration += 1;
  mounting?.controller.abort(new RuntimeMountCancelledError());
  mounting = undefined;
  const current = session;
  session = undefined;
  return enqueueRuntimeLifecycle(async () => await current?.dispose());
};
