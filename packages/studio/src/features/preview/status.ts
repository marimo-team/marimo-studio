import type {
  BrowserDiagnostic,
  RuntimeStatusSnapshot,
} from "@marimo-studio/protocol/browser-observations";

export interface PreviewStatus {
  diagnostics: readonly BrowserDiagnostic[];
  message: string;
  state: "loading" | "ready" | "warning" | "error";
}

const STARTING_MESSAGES = new Map([
  ["server", "Connecting to Python"],
  ["wasm", "Starting browser notebook"],
  ["zero-python", "Starting Prepared preview"],
]);

export const previewStartingMessage = (runtime: string): string =>
  STARTING_MESSAGES.get(runtime) ?? `Connecting to ${runtime}`;

const degradedMessage = (diagnostics: readonly BrowserDiagnostic[]): string => {
  const errors = diagnostics.filter((diagnostic) => diagnostic.severity === "error").length;
  if (errors === diagnostics.length) {
    return `Live with ${errors} ${errors === 1 ? "error" : "errors"}`;
  }
  if (errors === 0) {
    return `Live with ${diagnostics.length} ${diagnostics.length === 1 ? "warning" : "warnings"}`;
  }
  return `Live with ${diagnostics.length} ${diagnostics.length === 1 ? "issue" : "issues"}`;
};

export const previewStatus = (runtime: string, status: RuntimeStatusSnapshot): PreviewStatus => {
  const diagnostics = status.diagnostics;
  switch (status.phase) {
    case "connecting":
      return { diagnostics, message: previewStartingMessage(runtime), state: "loading" };
    case "synchronizing":
      return { diagnostics, message: "Updating preview", state: "loading" };
    case "ready":
      return { diagnostics, message: "Live", state: "ready" };
    case "degraded":
      return { diagnostics, message: degradedMessage(diagnostics), state: "warning" };
    case "failed":
      return { diagnostics, message: "Needs repair", state: "error" };
  }
};
