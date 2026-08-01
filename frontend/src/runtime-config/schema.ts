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

export interface ProjectionDiagnostic {
  code: string;
  severity: "warning" | "error";
  message: string;
  hint: string;
  view: string;
  projection: "cell" | "value";
  target: string;
  source: {
    path: string;
    line: number;
    column: number;
  };
}

export interface PresentationDiagnostic {
  code: string;
  severity: "warning" | "error";
  message: string;
  hint: string;
  view: string;
  scope: "presentation";
}

export interface HostDiagnostic {
  code: string;
  severity: "error";
  message: string;
  hint: string;
  view: string;
  scope: "host";
  target: string;
}

export interface RuntimeDiagnostic {
  code: string;
  severity: "warning" | "error";
  message: string;
  hint: string;
  view: string;
  scope: "runtime";
}

export type StudioDiagnostic =
  | ProjectionDiagnostic
  | PresentationDiagnostic
  | HostDiagnostic
  | RuntimeDiagnostic;

export interface RuntimeConfig {
  schema: 1;
  revision: string;
  view: string;
  views: string[];
  fileKey: string;
  runtimeUrl: string;
  supportUrl: string;
  cellBindings: Record<string, CellBindingConfig>;
  valueBindings: Record<string, ValueBindingConfig>;
  diagnostics: ProjectionDiagnostic[];
  appConfig: Record<string, unknown>;
  userConfig: Record<string, unknown>;
  configOverrides: Record<string, unknown>;
  serverToken: string;
  dev: boolean;
  mode: "edit" | "run";
  preserveSession: boolean;
}

export interface MountConfig {
  supportUrl: string;
  version: string;
  revision: string;
}

declare global {
  interface Window {
    __MARIMO_STUDIO_SESSION_ID__?: string;
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

const isProjectionDiagnostic = (
  value: unknown,
): value is ProjectionDiagnostic => {
  if (!isRecord(value) || !isRecord(value.source)) {
    return false;
  }
  return typeof value.code === "string" &&
    (value.severity === "warning" || value.severity === "error") &&
    typeof value.message === "string" &&
    typeof value.hint === "string" &&
    typeof value.view === "string" &&
    (value.projection === "cell" || value.projection === "value") &&
    typeof value.target === "string" &&
    typeof value.source.path === "string" &&
    typeof value.source.line === "number" &&
    Number.isInteger(value.source.line) &&
    typeof value.source.column === "number" &&
    Number.isInteger(value.source.column);
};

export const parseRuntimeConfig = (value: unknown): RuntimeConfig => {
  if (
    !isRecord(value) ||
    value.schema !== 1 ||
    typeof value.revision !== "string" ||
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
    !Array.isArray(value.diagnostics) ||
    !value.diagnostics.every(isProjectionDiagnostic) ||
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
