import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import { terminateProcessTree } from "./process-tree.mjs";

void test("Windows fallback waits for taskkill to terminate descendants", async () => {
  const calls = [];
  const spawnProcess = (command, args, options) => {
    calls.push({ command, args, options });
    const process = new EventEmitter();
    queueMicrotask(() => process.emit("exit", 0, null));
    return process;
  };
  const child = { pid: 4312, kill: () => assert.fail("child.kill must not run on Windows") };

  await terminateProcessTree(child, "SIGTERM", {
    platform: "win32",
    spawnProcess,
  });

  assert.deepEqual(calls, [
    {
      command: "taskkill.exe",
      args: ["/PID", "4312", "/T", "/F"],
      options: { stdio: "ignore", windowsHide: true },
    },
  ]);
});

void test(
  "Windows fallback teardown is bounded when taskkill stalls",
  { timeout: 1_000 },
  async () => {
    let killed = false;
    const spawnProcess = () => {
      const process = new EventEmitter();
      process.kill = () => {
        killed = true;
      };
      return process;
    };

    await assert.rejects(
      terminateProcessTree({ pid: 4312 }, "SIGTERM", {
        platform: "win32",
        spawnProcess,
        taskkillTimeoutMs: 10,
      }),
      /taskkill did not exit within 10ms/,
    );
    assert.equal(killed, true);
  },
);

void test("POSIX fallback signals the detached process group", async () => {
  const calls = [];
  const killProcess = (pid, signal) => calls.push([pid, signal]);
  const child = { pid: 4312, kill: () => assert.fail("child.kill must not run with a PID") };

  await terminateProcessTree(child, "SIGTERM", {
    killProcess,
    platform: "darwin",
  });

  assert.deepEqual(calls, [[-4312, "SIGTERM"]]);
});
