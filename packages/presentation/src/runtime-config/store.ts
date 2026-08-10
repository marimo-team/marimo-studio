import {
  parseMountConfig,
  type CellBindingConfig,
  type MountConfig,
  type ProjectionDiagnostic,
  type RuntimeConfig,
  type ValueBindingConfig,
} from "@marimo-studio/protocol/runtime-config";

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
  return (
    keys.length === Object.keys(right).length &&
    keys.every(
      (key) => left[key]?.kind === right[key]?.kind && left[key]?.value === right[key]?.value,
    )
  );
};

const sameValueBindings = (
  left: Record<string, ValueBindingConfig>,
  right: Record<string, ValueBindingConfig>,
): boolean => {
  const keys = Object.keys(left);
  return (
    keys.length === Object.keys(right).length &&
    keys.every(
      (key) =>
        left[key]?.variable === right[key]?.variable &&
        left[key]?.cell.kind === right[key]?.cell.kind &&
        left[key]?.cell.value === right[key]?.cell.value,
    )
  );
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

export const commitRuntimeConfig = (config: RuntimeConfig): RuntimeConfig => {
  const cellBindings =
    current && sameCellBindings(current.cellBindings, config.cellBindings)
      ? current.cellBindings
      : config.cellBindings;
  const valueBindings =
    current && sameValueBindings(current.valueBindings, config.valueBindings)
      ? current.valueBindings
      : config.valueBindings;
  const outputBindings =
    current && sameValueBindings(current.outputBindings, config.outputBindings)
      ? current.outputBindings
      : config.outputBindings;
  const cellsChanged = current?.cellBindings !== cellBindings;
  current =
    cellBindings === config.cellBindings &&
    valueBindings === config.valueBindings &&
    outputBindings === config.outputBindings
      ? config
      : { ...config, cellBindings, valueBindings, outputBindings };
  listeners.forEach((listener) => listener());
  if (cellsChanged) {
    cellListeners.forEach((listener) => listener());
  }
  return current;
};

export const getRuntimeCellBindings = (): Record<string, CellBindingConfig> =>
  getRuntimeConfig().cellBindings;

export const subscribeRuntimeCellBindings = (listener: Listener): (() => void) => {
  cellListeners.add(listener);
  return () => cellListeners.delete(listener);
};

declare global {
  var __MARIMO_MOUNT_CONFIG__: MountConfig;
}
