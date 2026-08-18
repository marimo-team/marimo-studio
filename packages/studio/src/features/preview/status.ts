import type {
  BrowserDiagnostic,
  RuntimeStatusSnapshot,
} from "@marimo-studio/protocol/browser-observations";

export interface PreviewStatus {
  message: string;
  state: "loading" | "ready" | "warning" | "error";
  title: string;
}

const STARTING_MESSAGES = new Map([
  ["server", "Connecting to server"],
  ["wasm", "Starting WebAssembly"],
]);

export const previewStartingMessage = (runtime: string): string =>
  STARTING_MESSAGES.get(runtime) ?? `Connecting to ${runtime}`;

const diagnosticTitle = (diagnostics: readonly BrowserDiagnostic[]): string =>
  diagnostics
    .map((diagnostic) => [diagnostic.message, diagnostic.hint].filter(Boolean).join(" "))
    .join("\n");

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
  const title = diagnosticTitle(status.diagnostics);
  switch (status.phase) {
    case "connecting":
      return { message: previewStartingMessage(runtime), state: "loading", title };
    case "synchronizing":
      return { message: "Synchronizing preview", state: "loading", title };
    case "ready":
      return { message: "Live", state: "ready", title };
    case "degraded":
      return { message: degradedMessage(status.diagnostics), state: "warning", title };
    case "failed":
      return { message: "Needs repair", state: "error", title };
  }
};
