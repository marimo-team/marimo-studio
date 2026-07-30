export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface CellBindingConfig {
  kind: "id" | "name";
  value: string;
}

export interface ValueBindingConfig {
  variable: string;
  cell: CellBindingConfig;
}

export interface RuntimeConfig {
  schema: 1;
  view: string;
  views: string[];
  fileKey: string;
  runtimeUrl: string;
  supportUrl: string;
  cellBindings: Record<string, CellBindingConfig>;
  valueBindings: Record<string, ValueBindingConfig>;
  appConfig: Record<string, unknown>;
  userConfig: Record<string, unknown>;
  configOverrides: Record<string, unknown>;
  serverToken: string;
  dev: boolean;
  mode: "edit" | "run";
  preserveSession: boolean;
}

declare global {
  interface Window {
    __MARIMO_STUDIO_SESSION_ID__?: string;
  }
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
): Promise<{ code: string; message: string; transient: boolean }> => {
  const payload: unknown = await response.clone().json().catch(() => undefined);
  return {
    code: isRecord(payload) && typeof payload.error === "string"
      ? payload.error
      : "runtime-config-failed",
    message: isRecord(payload) && typeof payload.message === "string"
      ? payload.message
      : (await response.text()).trim() || fallback,
    transient: isRecord(payload) && payload.transient === true,
  };
};

export class RuntimeConfigRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
  ) {
    super(message);
    this.name = "RuntimeConfigRequestError";
  }
}

export const runtimeConfigSessionId = ({
  connected,
  href,
}: {
  connected?: string;
  href?: string;
}): string | undefined => {
  if (connected) {
    return connected;
  }
  try {
    const url = new URL(href ?? "");
    if (url.searchParams.get("marimo_studio_resume") === "1") {
      return url.searchParams.get("session_id") ?? undefined;
    }
  } catch {
    return undefined;
  }
  return undefined;
};

const isCellBinding = (value: unknown): value is CellBindingConfig => {
  return isRecord(value) &&
    (value.kind === "id" || value.kind === "name") &&
    typeof value.value === "string";
};

const isValueBinding = (value: unknown): value is ValueBindingConfig => {
  return isRecord(value) &&
    typeof value.variable === "string" &&
    isCellBinding(value.cell);
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
    !isRecord(value.cellBindings) ||
    !Object.values(value.cellBindings).every(isCellBinding) ||
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

export const hasRuntimeConfig = (): boolean => current !== undefined;

export const subscribeRuntimeConfig = (listener: Listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

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

const publish = (config: RuntimeConfig): RuntimeConfig => {
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

export const fetchRuntimeConfig = async (
  supportUrl: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> => {
  const browser = globalThis as typeof globalThis & Window;
  const sessionId = runtimeConfigSessionId({
    connected: browser.__MARIMO_STUDIO_SESSION_ID__,
    href: browser.location?.href,
  });
  const response = await fetch(`${supportUrl}/config`, {
    cache: "no-store",
    headers: sessionId ? { "Marimo-Session-Id": sessionId } : undefined,
    signal,
  });
  if (!response.ok) {
    const detail = await responseError(
      response,
      `Runtime config failed with ${response.status}`,
    );
    throw new RuntimeConfigRequestError(
      detail.message,
      detail.code,
      detail.transient,
    );
  }
  return parseRuntimeConfig(await response.json());
};

const retryDelays = [100, 250, 500, 1_000];

const waitForRetry = (delay: number, signal?: AbortSignal): Promise<void> => {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The request was aborted", "AbortError"));
      return;
    }
    const aborted = () => {
      clearTimeout(timeout);
      reject(new DOMException("The request was aborted", "AbortError"));
    };
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", aborted);
      resolve();
    }, delay);
    signal?.addEventListener("abort", aborted, { once: true });
  });
};

export const fetchRuntimeConfigWithRetry = async (
  supportUrl: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> => {
  for (let attempt = 0;; attempt += 1) {
    try {
      return await fetchRuntimeConfig(supportUrl, signal);
    } catch (error) {
      if (
        !(error instanceof RuntimeConfigRequestError) ||
        !error.transient ||
        attempt >= retryDelays.length
      ) {
        throw error;
      }
      await waitForRetry(retryDelays[attempt], signal);
    }
  }
};

export const commitRuntimeConfig = publish;

export const getRuntimeCellBindings = (): Record<
  string,
  CellBindingConfig
> => {
  return getRuntimeConfig().cellBindings;
};

export const subscribeRuntimeCellBindings = (listener: Listener) => {
  cellListeners.add(listener);
  return () => cellListeners.delete(listener);
};

export const loadRuntimeConfig = async (): Promise<RuntimeConfig> => {
  return publish(await fetchRuntimeConfigWithRetry(mountConfig().supportUrl));
};

declare global {
  var __MARIMO_MOUNT_CONFIG__: MountConfig;
}
