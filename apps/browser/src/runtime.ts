import { startPresentation } from "@marimo-studio/presentation/runtime";
import { presentationRuntimes } from "@marimo-studio/presentation/runtimes";
import { createRuntimeRegistry } from "@marimo-studio/runtime";

import { zeroPythonRuntime } from "./zero-python/runtime.ts";

startPresentation(createRuntimeRegistry([...presentationRuntimes, zeroPythonRuntime]), async () => {
  const [{ bootstrapSession }, { BrowserSessionReplay }] = await Promise.all([
    import("@marimo-studio/marimo-frontend/session-bootstrap"),
    import("@marimo-studio/presentation/session-replay"),
  ]);
  return { bootstrap: bootstrapSession, replay: new BrowserSessionReplay() };
});
