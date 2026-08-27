import {
  parseMountConfig,
  type MountConfig,
  type ProjectionDiagnostic,
  type RuntimeConfig,
} from "@marimo-studio/protocol/runtime-config";

type Listener = () => void;

const listeners = new Set<Listener>();
const projectionListeners = new Set<Listener>();
const cellListeners = new Set<Listener>();
let current: RuntimeConfig | undefined;
let projectionConfig: RuntimeConfig | undefined;
let mount: MountConfig | undefined;

const sameCellRefs = (left: Record<string, string>, right: Record<string, string>): boolean => {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key]);
};

export const getMountConfig = (): MountConfig => {
  if (mount) {
    return mount;
  }
  mount = parseMountConfig(globalThis.__MARIMO_MOUNT_CONFIG__);
  return mount;
};

export const getSupportUrl = (): string => getMountConfig().supportUrl;

export const setSupportUrl = (supportUrl: string): void => {
  mount = { ...getMountConfig(), supportUrl };
};

export const getRuntimeConfig = (): RuntimeConfig => {
  if (!current) {
    throw new Error("Runtime config has not loaded");
  }
  return current;
};

export const getRuntimeDiagnostics = (): readonly ProjectionDiagnostic[] => {
  return getRuntimeConfig().diagnostics.map((diagnostic) => ({
    ...diagnostic,
    source: { ...diagnostic.source },
  }));
};

export const hasRuntimeConfig = (): boolean => current !== undefined;

export const subscribeRuntimeConfig = (listener: Listener): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const getRuntimeProjectionConfig = (): RuntimeConfig => {
  if (!projectionConfig) {
    throw new Error("Runtime projection config has not loaded");
  }
  return projectionConfig;
};

export const subscribeRuntimeProjectionConfig = (listener: Listener): (() => void) => {
  projectionListeners.add(listener);
  return () => projectionListeners.delete(listener);
};

export const commitRuntimeConfig = (config: RuntimeConfig): RuntimeConfig => {
  const cellRefs =
    current && sameCellRefs(current.runtimeBindings.cellRefs, config.runtimeBindings.cellRefs)
      ? current.runtimeBindings.cellRefs
      : config.runtimeBindings.cellRefs;
  const cellsChanged = current?.runtimeBindings.cellRefs !== cellRefs;
  current =
    cellRefs === config.runtimeBindings.cellRefs
      ? config
      : { ...config, runtimeBindings: { cellRefs } };
  // The server folds every projection behavior change into this revision.
  // Retaining its snapshot keeps presentation-only commits off the projection lane.
  const projectionChanged = projectionConfig?.projectionRevision !== current.projectionRevision;
  if (projectionChanged) {
    projectionConfig = current;
  }
  listeners.forEach((listener) => listener());
  if (projectionChanged) {
    projectionListeners.forEach((listener) => listener());
  }
  if (cellsChanged) {
    cellListeners.forEach((listener) => listener());
  }
  return current;
};

export const getRuntimeCellRefs = (): Record<string, string> =>
  getRuntimeConfig().runtimeBindings.cellRefs;

export const subscribeRuntimeCellRefs = (listener: Listener): (() => void) => {
  cellListeners.add(listener);
  return () => cellListeners.delete(listener);
};

declare global {
  var __MARIMO_MOUNT_CONFIG__: MountConfig;
}
