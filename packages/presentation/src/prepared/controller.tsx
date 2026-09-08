import type {
  ControlBindings as MarimoControlBindings,
  PreparedControlInput as MarimoPreparedControlInput,
  PreparedPresentationConfig,
  PreparedThemeSource,
} from "@marimo-studio/marimo-frontend/prepared-presentation";
import type { ValueReadError } from "@marimo-studio/protocol/value-read";

import {
  mountPreparedPresentation,
  releaseProjectedOutputResources,
} from "@marimo-studio/marimo-frontend/prepared-presentation";

import type { PreparedProjectionSnapshot } from "./records.ts";
import type { PreparedOutputOwners, PreparedResources } from "./resources.ts";

import { getCellHosts, setCellHostState } from "../cells/host.ts";
import { getOutputHosts, setOutputHostState } from "../outputs/host.ts";
import { getRuntimeConfig } from "../runtime-config/index.ts";
import { markValuePending, markValueRetainedError } from "../values/hosts.ts";
import { immutablePreparedSnapshot } from "./records.ts";
import { prepareProjectionResources } from "./resources.ts";
import {
  applyPreparedSnapshot,
  attempt,
  attemptAsync,
  failureWithCleanup,
  preparedFailure,
  releasePreparedOwners,
  throwCleanupErrors,
} from "./transaction.tsx";

export interface MountPreparedProjectionsOptions {
  readonly onControlInput?: (input: PreparedControlInput) => void;
  readonly onPeerControlInput?: (input: PreparedControlInput) => void;
  readonly presentation: PreparedPresentationConfig;
  readonly root: HTMLElement;
  readonly theme: PreparedThemeSource;
}

export type PreparedControlInput = MarimoPreparedControlInput;

export type PreparedControlBindings = MarimoControlBindings;

export interface ReplacePreparedProjectionOptions {
  readonly signal?: AbortSignal;
}

export interface PreparedProjectionHandle {
  checkpoint(): PreparedProjectionCheckpoint;
  replace(
    snapshot: PreparedProjectionSnapshot,
    options?: ReplacePreparedProjectionOptions,
  ): Promise<void>;
  restore(): Promise<void>;
  updateControlBindings(bindings: PreparedControlBindings): void;
  update(presentation: PreparedPresentationConfig): void;
  dispose(): Promise<void>;
}

export interface PreparedProjectionCheckpoint {
  restore(): Promise<void>;
  dispose(): void;
}

const immutableControlBindings = (bindings: PreparedControlBindings): PreparedControlBindings => {
  const copy = structuredClone(bindings);
  Object.values(copy).forEach((binding) => Object.freeze(binding.path));
  Object.values(copy).forEach(Object.freeze);
  return Object.freeze(copy);
};

const markPending = (snapshot: PreparedProjectionSnapshot): void => {
  const revision = getRuntimeConfig().projectionRevision;
  snapshot.values.forEach(({ selector }) => markValuePending(selector, revision));
  for (const host of getOutputHosts()) {
    setOutputHostState(host, host.hasChildNodes() ? "stale" : "loading", {
      selector: host.valueSelector,
    });
  }
  for (const host of getCellHosts()) {
    setCellHostState(host, host.hasChildNodes() ? "stale" : "loading", {
      alias: host.cellName,
    });
  }
};

const failure = (error: Error): ValueReadError => ({
  code: "prepared-projection-failed",
  message: error.message,
  hint: "Select another prepared state or rebuild this export.",
});

const markFailure = (snapshot: PreparedProjectionSnapshot, error: Error): void => {
  const detail = failure(error);
  const revision = getRuntimeConfig().projectionRevision;
  snapshot.values.forEach(({ selector }) => markValueRetainedError(selector, detail, revision));
  for (const host of getOutputHosts()) {
    host.dataset.marimoDiagnosticCode = detail.code;
    host.dataset.marimoDiagnosticMessage = detail.message;
    host.dataset.marimoDiagnosticHint = detail.hint;
    setOutputHostState(host, "error", {
      selector: host.valueSelector,
      ...detail,
    });
  }
  for (const host of getCellHosts()) {
    host.dataset.marimoDiagnosticCode = detail.code;
    host.dataset.marimoDiagnosticMessage = detail.message;
    host.dataset.marimoDiagnosticHint = detail.hint;
    setCellHostState(host, "error", {
      alias: host.cellName,
      ...detail,
    });
  }
};

const linkAbort = (controller: AbortController, signal: AbortSignal | undefined): (() => void) => {
  if (signal === undefined) {
    return () => {};
  }
  const abort = () => controller.abort(signal.reason);
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) {
    abort();
  }
  return () => signal.removeEventListener("abort", abort);
};

export interface PreparedProjectionDependencies {
  readonly mountPresentation: typeof mountPreparedPresentation;
  readonly releaseOutputResources: typeof releaseProjectedOutputResources;
}

export const createPreparedProjectionMount =
  (dependencies: PreparedProjectionDependencies) =>
  (options: MountPreparedProjectionsOptions): PreparedProjectionHandle => {
    const shell = dependencies.mountPresentation({
      ...options,
      onControlInput:
        options.onControlInput === undefined
          ? undefined
          : (input: MarimoPreparedControlInput) => options.onControlInput?.(input),
      onPeerControlInput:
        options.onPeerControlInput === undefined
          ? undefined
          : (input: MarimoPreparedControlInput) => options.onPeerControlInput?.(input),
    });
    let current: PreparedProjectionSnapshot | undefined;
    let currentResources: PreparedResources | undefined;
    let currentControlBindings = immutableControlBindings({});
    let currentOwners: PreparedOutputOwners = new Map();
    let active: AbortController | undefined;
    let queue: Promise<void> = Promise.resolve();
    let restoration: Promise<void> | undefined;
    let portalRevision = 0;
    let disposed = false;
    let disposal: Promise<void> | undefined;

    const applySnapshot = async (
      snapshot: PreparedProjectionSnapshot,
      resources: PreparedResources,
      replaceModels: boolean,
      signal?: AbortSignal,
    ): Promise<void> => {
      const application = await applyPreparedSnapshot({
        shell,
        snapshot,
        previousOwners: currentOwners,
        resources,
        portalRevision,
        release: dependencies.releaseOutputResources,
        replaceModels,
        signal,
      });
      portalRevision = application.portalRevision;
      if (!application.ok) {
        throw application.error;
      }
      currentOwners = application.owners;
    };

    const restoreCommitted = async (
      replaceModels: boolean,
      signal?: AbortSignal,
    ): Promise<void> => {
      if (current === undefined || currentResources === undefined) {
        signal?.throwIfAborted();
        shell.render(null);
        return;
      }
      await applySnapshot(current, currentResources, replaceModels, signal);
    };

    const perform = async (
      snapshot: PreparedProjectionSnapshot,
      controller: AbortController,
      prepared?: PreparedResources,
    ): Promise<void> => {
      controller.signal.throwIfAborted();
      const resources = prepared ?? prepareProjectionResources(snapshot);
      try {
        await applySnapshot(snapshot, resources, true, controller.signal);
        current = snapshot;
        currentResources = resources;
      } catch (error) {
        const cause = preparedFailure(error);
        const cleanupErrors: Error[] = [];
        await attemptAsync(cleanupErrors, () => restoreCommitted(false));
        if (!controller.signal.aborted) {
          attempt(cleanupErrors, () => markFailure(snapshot, cause));
        }
        throw failureWithCleanup(
          cause,
          cleanupErrors,
          "Prepared projection replacement and rollback failed",
        );
      }
    };

    const restore = (): Promise<void> => {
      if (disposed) {
        return Promise.resolve();
      }
      if (restoration !== undefined) {
        return restoration;
      }
      active?.abort(
        new DOMException("Prepared projection restoration superseded it", "AbortError"),
      );
      const controller = new AbortController();
      active = controller;
      const operation = queue.then(
        () => restoreCommitted(true, controller.signal),
        () => restoreCommitted(true, controller.signal),
      );
      queue = operation.catch(() => {});
      const tracked = operation.finally(() => {
        if (active === controller) {
          active = undefined;
        }
        if (restoration === tracked) {
          restoration = undefined;
        }
      });
      restoration = tracked;
      return tracked;
    };

    const replace = (
      value: PreparedProjectionSnapshot,
      replaceOptions: ReplacePreparedProjectionOptions = {},
    ): Promise<void> => {
      const snapshot = immutablePreparedSnapshot(value);
      return replacePrepared(snapshot, undefined, replaceOptions);
    };

    const replacePrepared = (
      snapshot: PreparedProjectionSnapshot,
      resources: PreparedResources | undefined,
      replaceOptions: ReplacePreparedProjectionOptions = {},
    ): Promise<void> => {
      if (disposed) {
        return Promise.resolve();
      }
      active?.abort(
        new DOMException("Prepared projection generation was superseded", "AbortError"),
      );
      const controller = new AbortController();
      active = controller;
      const unlink = linkAbort(controller, replaceOptions.signal);
      markPending(snapshot);
      const operation = queue.then(
        () => perform(snapshot, controller, resources),
        () => perform(snapshot, controller, resources),
      );
      queue = operation.catch(() => {});
      return operation.finally(() => {
        unlink();
        if (active === controller) {
          active = undefined;
        }
      });
    };

    const applyControlBindings = (bindings: PreparedControlBindings): void => {
      if (disposed) {
        return;
      }
      shell.updateControlBindings(bindings);
      currentControlBindings = bindings;
    };

    const updateControlBindings = (bindings: PreparedControlBindings): void => {
      applyControlBindings(immutableControlBindings(bindings));
    };

    const checkpoint = (): PreparedProjectionCheckpoint => {
      if (current === undefined || currentResources === undefined) {
        throw new Error("Prepared projections require a committed snapshot before checkpointing");
      }
      const modelCheckpoint = shell.models.snapshot();
      let snapshot: PreparedProjectionSnapshot | undefined = current;
      let resources: PreparedResources | undefined = {
        files: structuredClone(modelCheckpoint.files),
        modelNotifications: structuredClone([...modelCheckpoint.modelNotifications]),
        uiValues: structuredClone(shell.uiValues.snapshot()),
        modelCheckpoint,
      };
      let bindings: PreparedControlBindings | undefined = currentControlBindings;
      let restoration: Promise<void> | undefined;
      let checkpointDisposed = false;
      const restoreCheckpoint = (): Promise<void> => {
        if (checkpointDisposed || disposed) {
          return Promise.resolve();
        }
        if (restoration !== undefined) {
          return restoration;
        }
        const targetSnapshot = snapshot;
        const targetResources = resources;
        const targetBindings = bindings;
        if (
          targetSnapshot === undefined ||
          targetResources === undefined ||
          targetBindings === undefined
        ) {
          return Promise.resolve();
        }
        const operation = replacePrepared(targetSnapshot, targetResources).then(() => {
          applyControlBindings(targetBindings);
        });
        const tracked = operation.finally(() => {
          if (restoration === tracked) {
            restoration = undefined;
          }
        });
        restoration = tracked;
        return tracked;
      };
      return Object.freeze({
        restore: restoreCheckpoint,
        dispose() {
          if (checkpointDisposed) {
            return;
          }
          checkpointDisposed = true;
          snapshot = undefined;
          resources = undefined;
          bindings = undefined;
        },
      });
    };

    const dispose = (): Promise<void> => {
      disposal ??= (async () => {
        disposed = true;
        active?.abort(new DOMException("Prepared projections were disposed", "AbortError"));
        const errors: Error[] = [];
        await attemptAsync(errors, () => queue);
        attempt(errors, () =>
          releasePreparedOwners(currentOwners, dependencies.releaseOutputResources),
        );
        await attemptAsync(errors, () => shell.dispose());
        current = undefined;
        currentResources = undefined;
        currentControlBindings = immutableControlBindings({});
        currentOwners = new Map();
        throwCleanupErrors(errors, "Prepared projection disposal failed");
      })();
      return disposal;
    };

    return Object.freeze({
      checkpoint,
      replace,
      restore,
      updateControlBindings,
      update: (presentation: PreparedPresentationConfig) => shell.update(presentation),
      dispose,
    });
  };

export const mountPreparedProjections = createPreparedProjectionMount({
  mountPresentation: mountPreparedPresentation,
  releaseOutputResources: releaseProjectedOutputResources,
});
