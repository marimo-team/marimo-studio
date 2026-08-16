import type { BrowserDiagnostic } from "@marimo-studio/protocol/browser-observations";
import type { ProjectionDiagnostic } from "@marimo-studio/protocol/runtime-config";

import type {
  HostDiagnostic,
  PresentationDiagnostic,
  RuntimeDiagnostic,
  StudioDiagnostic,
} from "./diagnostics.ts";

interface DiagnosticSources {
  configured: readonly ProjectionDiagnostic[];
  presentation?: PresentationDiagnostic;
  runtime?: RuntimeDiagnostic;
  view: string;
}

export const collectStudioDiagnostics = ({
  configured,
  presentation,
  runtime,
  view,
}: DiagnosticSources): readonly StudioDiagnostic[] => {
  const configuredKeys = new Set(
    configured.map((diagnostic) => `${diagnostic.code}\u0000${diagnostic.target}`),
  );
  const hosts = Array.from(
    document.querySelectorAll<HTMLElement>("[data-marimo-diagnostic-code]"),
  ).flatMap((host): Array<HostDiagnostic | PresentationDiagnostic> => {
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
    if (host.dataset.marimoDiagnosticScope === "presentation") {
      return [
        {
          scope: "presentation",
          code,
          severity: "error",
          message,
          hint: host.dataset.marimoDiagnosticHint ?? "",
          view,
        },
      ];
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
  return [
    ...configured,
    ...hosts,
    ...(runtime ? [{ ...runtime }] : []),
    ...(presentation ? [{ ...presentation }] : []),
  ];
};

export const toBrowserDiagnostics = (
  diagnostics: readonly StudioDiagnostic[],
): BrowserDiagnostic[] => {
  const maximum = 200;
  const included = diagnostics.length > maximum ? diagnostics.slice(0, maximum - 1) : diagnostics;
  const result = included.map((diagnostic): BrowserDiagnostic => {
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
    if ("target" in diagnostic) {
      browserDiagnostic.target = diagnostic.target;
    }
    if ("source" in diagnostic) {
      browserDiagnostic.source = {
        ...diagnostic.source,
        line: Math.max(0, diagnostic.source.line),
        column: Math.max(0, diagnostic.source.column),
      };
    }
    return browserDiagnostic;
  });
  if (diagnostics.length > maximum) {
    const omitted = diagnostics.length - included.length;
    result.push({
      code: "browser-diagnostics-truncated",
      severity: "error",
      message: `${omitted} additional browser diagnostics were omitted.`,
      hint: "Fix repeated rendered-view errors, then rerun the analysis.",
      view: diagnostics[0]?.view ?? "unknown",
      scope: "presentation",
    });
  }
  return result;
};
