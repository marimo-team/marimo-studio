import type { ProjectionDiagnostic } from "@marimo-studio/protocol/runtime-config";

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
