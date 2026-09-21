import type { ProjectionDiagnostic } from "@marimo-studio/protocol/runtime-config";
import type { BrowserDiagnostic } from "@marimo-studio/protocol/runtime-status";

import type {
  HostDiagnostic,
  PresentationDiagnostic,
  RuntimeDiagnostic,
  StudioDiagnostic,
} from "./diagnostics.ts";

interface DiagnosticSources {
  configured: readonly ProjectionDiagnostic[];
  hosts: readonly HTMLElement[];
  presentation: readonly PresentationDiagnostic[];
  runtime?: RuntimeDiagnostic;
  view: string;
}

export const collectStudioDiagnostics = ({
  configured,
  hosts,
  presentation,
  runtime,
  view,
}: DiagnosticSources): readonly StudioDiagnostic[] => {
  const configuredKeys = new Set(
    configured.map((diagnostic) => `${diagnostic.code}\u0000${diagnostic.target}`),
  );
  const hostDiagnostics = hosts.flatMap((host): HostDiagnostic[] => {
    const code = host.dataset.marimoDiagnosticCode;
    const message = host.dataset.marimoDiagnosticMessage;
    let target = host.getAttribute("mo-value") ?? "";
    if (host.matches("marimo-cell")) {
      target = host.getAttribute("name") ?? "";
    } else if (host.matches("marimo-output")) {
      target = host.getAttribute("value") ?? "";
    }
    if (!code || !message || configuredKeys.has(`${code}\u0000${target}`)) {
      return [];
    }
    return [
      {
        scope: "host",
        code,
        severity: "error",
        message,
        hint: host.dataset.marimoDiagnosticHint ?? "",
        view,
        target,
      },
    ];
  });
  return [...configured, ...hostDiagnostics, ...(runtime ? [{ ...runtime }] : []), ...presentation];
};

export const toBrowserDiagnostics = (
  diagnostics: readonly StudioDiagnostic[],
): BrowserDiagnostic[] => {
  const maximum = 200;
  const included = diagnostics.length > maximum ? diagnostics.slice(0, maximum - 1) : diagnostics;
  const result = included.map(toBrowserDiagnostic);
  if (diagnostics.length > maximum) {
    const omitted = diagnostics.length - included.length;
    result.push({
      code: "browser-diagnostics-truncated",
      severity: "error",
      message: `${omitted} additional browser diagnostics were omitted.`,
      hint: "Fix repeated rendered-view errors, then rerun validation.",
      view: diagnostics[0]?.view ?? "unknown",
      scope: "presentation",
    });
  }
  return result;
};

export const toBrowserDiagnostic = (diagnostic: StudioDiagnostic): BrowserDiagnostic => {
  const browserDiagnostic: BrowserDiagnostic = {
    code: diagnostic.code,
    severity: diagnostic.severity,
    message: diagnostic.message,
    hint: diagnostic.hint,
    view: diagnostic.view,
    scope: "scope" in diagnostic ? diagnostic.scope : "projection",
  };
  if ("projection" in diagnostic) {
    browserDiagnostic.projection = diagnostic.projection;
  }
  if ("details" in diagnostic && diagnostic.details !== undefined) {
    browserDiagnostic.details = structuredClone(diagnostic.details);
  }
  if ("target" in diagnostic) {
    browserDiagnostic.target = diagnostic.target;
  }
  if ("source" in diagnostic && diagnostic.source !== undefined) {
    browserDiagnostic.source = {
      ...diagnostic.source,
      line: Math.max(0, diagnostic.source.line),
      column: Math.max(0, diagnostic.source.column),
    };
  }
  return browserDiagnostic;
};
