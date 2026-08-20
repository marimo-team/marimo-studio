import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { isWasmRpcTimeout, retryWasmRpc } from "../src/wasm-rpc.ts";

test("WebAssembly RPC reads retry transient worker deadlines", async () => {
  let attempts = 0;
  const value = await retryWasmRpc(async () => {
    attempts += 1;
    if (attempts < 3) {
      throw new Error("RPC request timed out.");
    }
    return "ready";
  });

  assert.equal(value, "ready");
  assert.equal(attempts, 3);
});

test("WebAssembly RPC retries preserve terminal errors", async () => {
  const failure = new Error("The notebook bridge failed.");

  await assert.rejects(
    retryWasmRpc(async () => Promise.reject(failure)),
    failure,
  );
  assert.equal(isWasmRpcTimeout(failure), false);
});

test("WebAssembly RPC cancellation settles a stalled active invocation", async () => {
  const controller = new AbortController();
  const waiting = retryWasmRpc(() => new Promise<never>(() => {}), controller.signal);
  const cancelled = assert.rejects(waiting, { name: "AbortError" });

  controller.abort(new DOMException("Query superseded", "AbortError"));

  await cancelled;
});
