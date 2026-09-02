export const shouldRecordConsoleMessage = (type: string, message: string): boolean =>
  message.includes("UIElementRegistry missing entry") ||
  (["warning", "error"].includes(type) && !message.startsWith("Failed to load resource:"));
