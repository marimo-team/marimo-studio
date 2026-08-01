import type {
  CellBindingConfig,
  MountConfig,
  ProjectionDiagnostic,
  RuntimeConfig,
  ValueBindingConfig,
} from "./schema.ts";

type Listener = () => void;

const listeners = new Set<Listener>();
const cellListeners = new Set<Listener>();
let current: RuntimeConfig | undefined;
let mount: MountConfig | undefined;

const sameCellBindings = (
  left: Record<string, CellBindingConfig>,
  right: Record<string, CellBindingConfig>,
): boolean => {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length &&
    keys.every((key) =>
      left[key]?.kind === right[key]?.kind &&
      left[key]?.value === right[key]?.value
    );
};

const sameValueBindings = (
  left: Record<string, ValueBindingConfig>,
  right: Record<string, ValueBindingConfig>,
): boolean => {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length &&
    keys.every((key) =>
      left[key]?.variable === right[key]?.variable &&
      left[key]?.cell.kind === right[key]?.cell.kind &&
      left[key]?.cell.value === right[key]?.cell.value
    );
};

export const getMountConfig = (): MountConfig => {
  if (mount) {
    return mount;
  }
  const value = globalThis.__MARIMO_MOUNT_CONFIG__;
  if (
    typeof value !== "object" ||
    value === null ||
    typeof value.supportUrl !== "string" ||
    typeof value.version !== "string" ||
    typeof value.revision !== "string"
  ) {
    throw new Error("Runtime mount config has an invalid shape");
  }
  mount = value;
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

export const subscribeRuntimeConfig = (listener: Listener): () => void => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

export const commitRuntimeConfig = (config: RuntimeConfig): RuntimeConfig => {
  const cellBindings = current &&
      sameCellBindings(current.cellBindings, config.cellBindings)
    ? current.cellBindings
    : config.cellBindings;
  const valueBindings = current &&
      sameValueBindings(current.valueBindings, config.valueBindings)
    ? current.valueBindings
    : config.valueBindings;
  const cellsChanged = current?.cellBindings !== cellBindings;
  current = cellBindings === config.cellBindings &&
      valueBindings === config.valueBindings
    ? config
    : { ...config, cellBindings, valueBindings };
  listeners.forEach((listener) => listener());
  if (cellsChanged) {
    cellListeners.forEach((listener) => listener());
  }
  return current;
};

export const getRuntimeCellBindings = (): Record<
  string,
  CellBindingConfig
> => getRuntimeConfig().cellBindings;

export const subscribeRuntimeCellBindings = (
  listener: Listener,
): () => void => {
  cellListeners.add(listener);
  return () => cellListeners.delete(listener);
};

declare global {
  var __MARIMO_MOUNT_CONFIG__: MountConfig;
}
