import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import { Logger } from "../src/runtime-logger";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Marimo runtime logging", () => {
  test("keeps routine runtime traffic quiet while forwarding failures", () => {
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    Logger.debug("[rpc] Worker -> Parent", { id: "kernelMessage" });
    Logger.warn("useConnectionTransport is unmounting. This likely means there is a bug.");
    Logger.warn("WebSocket closed", undefined, undefined);
    Logger.warn("[iframe] localStorage unavailable - using fallback storage");
    Logger.warn("[iframe] Fullscreen API unavailable");
    Logger.get("iframe").warn("localStorage unavailable - using fallback storage");
    Logger.get("iframe").warn("Fullscreen API unavailable");
    Logger.warn("Not running in a secure context; interrupts are not available.");
    Logger.warn("WebSocket closed", 1006, "network failure");

    expect(debug).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith("WebSocket closed", 1006, "network failure");
  });
});
