import { EventEmitter } from "node:events";
import { expect, test } from "vite-plus/test";

import { observeServerExit } from "../scripts/server-exit.mjs";

test("an unexpected clean server exit remains a lifecycle failure at teardown", () => {
  const child = new EventEmitter();
  const exit = observeServerExit(child, () => "server stopped");
  child.emit("exit", 0, null);

  expect(exit.shutdown()?.message).toContain("exited unexpectedly with 0");
  expect(exit.shutdown()?.message).toContain("server stopped");
});

test("server shutdown preserves the first startup error", () => {
  const failedChild = new EventEmitter();
  const failed = observeServerExit(failedChild, () => "");
  const error = new Error("server launch failed");
  failedChild.emit("error", error);
  failedChild.emit("exit", 1, null);
  expect(failed.shutdown()).toBe(error);
});

test("server shutdown accepts owned termination", () => {
  const child = new EventEmitter();
  const exit = observeServerExit(child, () => "");
  expect(exit.shutdown()).toBeUndefined();
  child.emit("exit", null, "SIGTERM");
  expect(exit.shutdown()).toBeUndefined();
});
