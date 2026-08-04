export const exposeRuntimeSession = (sessionId: string, enabled: boolean): (() => void) => {
  if (!enabled) {
    return () => {};
  }
  const browser = globalThis as typeof globalThis & Window;
  const previous = browser.__MARIMO_STUDIO_SESSION_ID__;
  browser.__MARIMO_STUDIO_SESSION_ID__ = sessionId;
  return () => {
    if (browser.__MARIMO_STUDIO_SESSION_ID__ !== sessionId) {
      return;
    }
    if (previous === undefined) {
      delete browser.__MARIMO_STUDIO_SESSION_ID__;
    } else {
      browser.__MARIMO_STUDIO_SESSION_ID__ = previous;
    }
  };
};
