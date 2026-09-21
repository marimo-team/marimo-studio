import type { JsonValue, ProjectionDiagnostic } from "@marimo-studio/protocol/runtime-config";

export interface PresentationDiagnostic {
  code: string;
  severity: "warning" | "error";
  message: string;
  hint: string;
  view: string;
  scope: "presentation";
  source?: ProjectionDiagnostic["source"];
  details?: Record<string, JsonValue>;
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
  details?: Record<string, JsonValue>;
}

export interface MountDeclarationDiagnostic {
  code: string;
  severity: "error";
  message: string;
  hint: string;
  view: string;
  scope: "projection";
  projection: "cell" | "value" | "output";
  source: { path: string; line: number; column: number };
}

export type StudioDiagnostic =
  | ProjectionDiagnostic
  | MountDeclarationDiagnostic
  | PresentationDiagnostic
  | HostDiagnostic
  | RuntimeDiagnostic;
