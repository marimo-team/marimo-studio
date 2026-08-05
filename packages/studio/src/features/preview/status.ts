export interface PreviewStatus {
  message: string;
  state: "loading" | "ready" | "warning" | "error";
  title: string;
}

const STARTING_MESSAGES: Readonly<Record<string, string>> = {
  server: "Connecting to server",
  wasm: "Starting WebAssembly",
};

export const previewStartingMessage = (runtime: string): string =>
  STARTING_MESSAGES[runtime] ?? `Connecting to ${runtime}`;

export const previewStartingStatus = (runtime: string): PreviewStatus => ({
  message: previewStartingMessage(runtime),
  state: "loading",
  title: "",
});
