import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import { PROJECTED_OUTPUT_FUNCTION_ABORT_MESSAGE } from "../src/projected-output-function-gate.ts";
import { Logger } from "../src/runtime-logger";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Marimo runtime logging", () => {
  test("keeps routine runtime traffic quiet while forwarding failures", () => {
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    Logger.debug("[rpc] Worker -> Parent", { id: "kernelMessage" });
    Logger.warn("useConnectionTransport is unmounting. This likely means there is a bug.");
    Logger.warn("WebSocket closed", undefined, undefined);
    Logger.warn("[iframe] localStorage unavailable - using fallback storage");
    Logger.warn("[iframe] Fullscreen API unavailable");
    Logger.warn("Not running in a secure context; interrupts are not available.");
    Logger.warn("WebSocket closed", 1006, "network failure");
    Logger.error(new DOMException(PROJECTED_OUTPUT_FUNCTION_ABORT_MESSAGE, "AbortError"));
    const runtimeFailure = new Error("runtime failure");
    Logger.error(runtimeFailure);

    expect(debug).not.toHaveBeenCalled();
    expect(error).toHaveBeenCalledOnce();
    expect(error).toHaveBeenCalledWith(runtimeFailure);
    expect(warn).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith("WebSocket closed", 1006, "network failure");
  });
});
