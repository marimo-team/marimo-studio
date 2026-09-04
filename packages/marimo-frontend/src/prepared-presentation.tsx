import type { ReactNode } from "react";

import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";

import type { ControlBindings } from "./control-endpoint-core.ts";
import type { PreparedCellPresentationSnapshot } from "./prepared-cell.tsx";
import type {
  PreparedControlInput,
  PreparedControlInputListener,
  PreparedUiValuesHandle,
} from "./prepared-controls.ts";
import type {
  PreparedModelGraphFactory,
  PreparedModelLifecycleHandle,
  PreparedModelLifecycleNotification,
  PreparedModelResources,
} from "./prepared-models.ts";
import type { MarimoPresentationConfig, MarimoThemeSource } from "./presentation-shell.tsx";
import type { MarimoCellOutputSnapshot } from "./projected-output.tsx";

import { PreparedCellPresentation } from "./prepared-cell.tsx";
import { createPreparedUiValues, installPreparedControlBridge } from "./prepared-controls.ts";
import { createPreparedModelLifecycle, PreparedModelGraphCheckpoint } from "./prepared-models.ts";
import {
  configureMarimoPresentation,
  configureMarimoTheme,
  initializeMarimoPresentation,
  MarimoPresentationProviders,
} from "./presentation-shell.tsx";
import {
  ProjectedOutputArea,
  reconcileProjectedOutput,
  releaseProjectedOutputResources,
  toMarimoCellOutput,
} from "./projected-output.tsx";
import { createStaticRequests, requestClientAtom, store } from "./upstream/presentation.ts";
import "./upstream/style.ts";

export type { PreparedModelLifecycleNotification };
export type { PreparedModelResources };
export type { PreparedModelGraphFactory };
export type { ControlBinding, ControlBindings, ControlPathStep } from "./control-endpoint-core.ts";
export type { PreparedControlInput, PreparedControlInputListener };
export type { MarimoCellOutputSnapshot, PreparedCellPresentationSnapshot };
export {
  PreparedCellPresentation,
  PreparedModelGraphCheckpoint,
  ProjectedOutputArea,
  reconcileProjectedOutput,
  releaseProjectedOutputResources,
  toMarimoCellOutput,
};
export type PreparedPresentationConfig = MarimoPresentationConfig;
export type PreparedThemeSource = MarimoThemeSource;

export interface MountPreparedPresentationOptions {
  readonly createModelGraph: PreparedModelGraphFactory;
  readonly presentation: PreparedPresentationConfig;
  readonly onControlInput?: PreparedControlInputListener;
  readonly onPeerControlInput?: PreparedControlInputListener;
  readonly render?: ReactNode;
  readonly root: HTMLElement;
  readonly theme: PreparedThemeSource;
}

export interface PreparedPresentationHandle {
  readonly models: PreparedModelLifecycleHandle;
  readonly uiValues: PreparedUiValuesHandle;
  render(content: ReactNode): void;
  updateControlBindings(bindings: ControlBindings): void;
  update(presentation: PreparedPresentationConfig): void;
  dispose(): Promise<void>;
}

let activeOwner: object | undefined;

export const mountPreparedPresentation = (
  options: MountPreparedPresentationOptions,
): PreparedPresentationHandle => {
  if (options.root.ownerDocument !== document) {
    throw new Error("Prepared presentations require a root in the current document");
  }
  if (activeOwner) {
    throw new Error("A prepared presentation is already mounted in this page");
  }
  const owner = {};
  activeOwner = owner;
  let presentation = options.presentation;
  let disposed = false;
  let disposal: Promise<void> | undefined;
  let stopTheme = () => {};
  let stopControls = () => {};
  let updateControlBindings = (_bindings: ControlBindings) => {};
  let models: PreparedModelLifecycleHandle | undefined;
  let uiValues: PreparedUiValuesHandle | undefined;
  let root: ReturnType<typeof createRoot> | undefined;
  const previousRequests = store.get(requestClientAtom);

  try {
    initializeMarimoPresentation();
    configureMarimoPresentation(presentation, "read", "read", options.theme.current());
    store.set(requestClientAtom, createStaticRequests());
    models = createPreparedModelLifecycle(options.createModelGraph);
    uiValues = createPreparedUiValues();
    const preparedRoot = createRoot(options.root);
    root = preparedRoot;
    const syncTheme = () => configureMarimoTheme(presentation, options.theme.current());
    stopTheme = options.theme.subscribe(syncTheme);
    const controlBridge = installPreparedControlBridge({
      onControlInput: options.onControlInput,
      onPeerControlInput: options.onPeerControlInput,
    });
    stopControls = () => controlBridge.dispose();
    updateControlBindings = (bindings) => controlBridge.updateControlBindings(bindings);
    flushSync(() => {
      preparedRoot.render(
        <MarimoPresentationProviders>{options.render ?? null}</MarimoPresentationProviders>,
      );
    });
    models.activate();
  } catch (error) {
    const errors: unknown[] = [error];
    const rollback = (action: () => void): void => {
      try {
        action();
      } catch (rollbackError) {
        errors.push(rollbackError);
      }
    };
    rollback(stopControls);
    rollback(stopTheme);
    rollback(() => uiValues?.dispose());
    rollback(() => root?.unmount());
    rollback(() => store.set(requestClientAtom, previousRequests));
    rollback(() => models?.abortSetup());
    if (activeOwner === owner) {
      activeOwner = undefined;
    }
    if (errors.length > 1) {
      throw new AggregateError(errors, "Prepared presentation mount and rollback failed");
    }
    throw error;
  }

  const render = (content: ReactNode): void => {
    if (disposed) {
      return;
    }
    flushSync(() => {
      root.render(<MarimoPresentationProviders>{content}</MarimoPresentationProviders>);
    });
  };
  const dispose = (): Promise<void> => {
    disposal ??= (async () => {
      disposed = true;
      const errors: unknown[] = [];
      try {
        root.unmount();
      } catch (error) {
        errors.push(error);
      }
      try {
        stopTheme();
      } catch (error) {
        errors.push(error);
      }
      try {
        stopControls();
      } catch (error) {
        errors.push(error);
      }
      try {
        uiValues.dispose();
      } catch (error) {
        errors.push(error);
      }
      try {
        store.set(requestClientAtom, previousRequests);
      } catch (error) {
        errors.push(error);
      }
      try {
        await models.dispose();
      } catch (error) {
        errors.push(error);
      }
      if (activeOwner === owner) {
        activeOwner = undefined;
      }
      if (errors.length === 1) {
        throw errors[0];
      }
      if (errors.length > 1) {
        throw new AggregateError(errors, "Prepared presentation disposal failed");
      }
    })();
    return disposal;
  };

  return Object.freeze({
    models,
    uiValues,
    render,
    updateControlBindings,
    update(next: PreparedPresentationConfig) {
      if (disposed) {
        return;
      }
      presentation = next;
      configureMarimoPresentation(presentation, "read", "read", options.theme.current());
    },
    dispose,
  });
};
