const RELOAD_CODES = new Set([
  "presentation-revision-mismatch",
  "presentation-revision-unavailable",
]);

export const runtimeStartupRecovery = (code: string): "reload" | "retry" =>
  RELOAD_CODES.has(code) ? "reload" : "retry";
