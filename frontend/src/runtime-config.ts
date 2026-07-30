export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ValueBindingConfig {
  variable: string;
  cellId: string;
}

export interface RuntimeConfig {
  schema: 1;
  view: string;
  views: string[];
  fileKey: string;
  runtimeUrl: string;
  supportUrl: string;
  cells: Record<string, string>;
  valueBindings: Record<string, ValueBindingConfig>;
  appConfig: Record<string, unknown>;
  userConfig: Record<string, unknown>;
  configOverrides: Record<string, unknown>;
  serverToken: string;
  dev: boolean;
  mode: "edit" | "run";
  preserveSession: boolean;
}

interface MountConfig {
  supportUrl: string;
  version: string;
}

type Listener = () => void;

const listeners = new Set<Listener>();
const cellListeners = new Set<Listener>();
let current: RuntimeConfig | undefined;
let mount: MountConfig | undefined;

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value);
};

const responseError = async (
  response: Response,
  fallback: string,
): Promise<string> => {
  const payload: unknown = await response.clone().json().catch(() => undefined);
  if (isRecord(payload) && typeof payload.message === "string") {
    return payload.message;
  }
  return (await response.text()).trim() || fallback;
};

const isValueBinding = (value: unknown): value is ValueBindingConfig => {
  return isRecord(value) &&
    typeof value.variable === "string" &&
    typeof value.cellId === "string";
};

export const parseRuntimeConfig = (value: unknown): RuntimeConfig => {
  if (
    !isRecord(value) ||
    value.schema !== 1 ||
    typeof value.view !== "string" ||
    !Array.isArray(value.views) ||
    !value.views.every((view) => typeof view === "string") ||
    typeof value.fileKey !== "string" ||
    typeof value.runtimeUrl !== "string" ||
    typeof value.supportUrl !== "string" ||
    !isRecord(value.cells) ||
    !Object.values(value.cells).every((cell) => typeof cell === "string") ||
    !isRecord(value.valueBindings) ||
    !Object.values(value.valueBindings).every(isValueBinding) ||
    !isRecord(value.appConfig) ||
    !isRecord(value.userConfig) ||
    !isRecord(value.configOverrides) ||
    typeof value.serverToken !== "string" ||
    typeof value.dev !== "boolean" ||
    (value.mode !== "edit" && value.mode !== "run") ||
    typeof value.preserveSession !== "boolean"
  ) {
    throw new Error("Runtime config has an invalid shape");
  }
  return value as unknown as RuntimeConfig;
};

const mountConfig = (): MountConfig => {
  if (mount) {
    return mount;
  }
  const value = globalThis.__MARIMO_MOUNT_CONFIG__;
  if (
    !isRecord(value) ||
    typeof value.supportUrl !== "string" ||
    typeof value.version !== "string"
  ) {
    throw new Error("Runtime mount config has an invalid shape");
  }
  mount = value as unknown as MountConfig;
  return mount;
};

export const getSupportUrl = (): string => mountConfig().supportUrl;

export const setSupportUrl = (supportUrl: string): void => {
  mount = { ...mountConfig(), supportUrl };
};

export const getRuntimeConfig = (): RuntimeConfig => {
  if (!current) {
    throw new Error("Runtime config has not loaded");
  }
  return current;
};

export const subscribeRuntimeConfig = (listener: Listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

const sameStringRecord = (
  left: Record<string, string>,
  right: Record<string, string>,
): boolean => {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length &&
    keys.every((key) => left[key] === right[key]);
};

const publish = (config: RuntimeConfig): RuntimeConfig => {
  const cells = current && sameStringRecord(current.cells, config.cells)
    ? current.cells
    : config.cells;
  const cellsChanged = current?.cells !== cells;
  current = cells === config.cells ? config : { ...config, cells };
  listeners.forEach((listener) => listener());
  if (cellsChanged) {
    cellListeners.forEach((listener) => listener());
  }
  return current;
};

export const fetchRuntimeConfig = async (
  supportUrl: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> => {
  const response = await fetch(`${supportUrl}/config`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(
      await responseError(
        response,
        `Runtime config failed with ${response.status}`,
      ),
    );
  }
  return parseRuntimeConfig(await response.json());
};

export const commitRuntimeConfig = publish;

export const getRuntimeCells = (): Record<string, string> => {
  return getRuntimeConfig().cells;
};

export const subscribeRuntimeCells = (listener: Listener) => {
  cellListeners.add(listener);
  return () => cellListeners.delete(listener);
};

export const loadRuntimeConfig = async (): Promise<RuntimeConfig> => {
  return publish(await fetchRuntimeConfig(mountConfig().supportUrl));
};

declare global {
  var __MARIMO_MOUNT_CONFIG__: MountConfig;
}
