import { Socket } from "node:net";
import { expect, test, vi } from "vite-plus/test";

import { portIsOpen, processEnvironmentContains } from "../scripts/process-group.ts";

test("treats an unreadable Linux process environment as unknown", () => {
  const readFailure = Object.assign(new Error("permission denied"), { code: "EACCES" });

  expect(
    processEnvironmentContains(123, "OWNER", "nonce", {
      platform: "linux",
      readFile: () => {
        throw readFailure;
      },
    }),
  ).toBeUndefined();
});

test.each(["deadline", "ETIMEDOUT", "ECONNREFUSED"])(
  "only connection refusal proves a port closed: %s",
  async (outcome) => {
    vi.useFakeTimers();
    const socket = new Socket();
    try {
      const probe = portIsOpen(4321, () => socket);
      if (outcome === "deadline") await vi.advanceTimersByTimeAsync(1000);
      else socket.emit("error", Object.assign(new Error(outcome), { code: outcome }));
      expect(await probe).toBe(outcome !== "ECONNREFUSED");
      expect(socket.destroyed).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  },
);
