import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { retry } from "../src/retry.ts";

test("a selected transient state can outlive the finite retry schedule", async () => {
  let attempts = 0;

  const result = await retry({
    operation: () => {
      attempts += 1;
      return attempts < 4 ? Promise.reject(new Error("pending")) : Promise.resolve("ready");
    },
    delays: [0],
    retryWhen: () => true,
    retryAfterExhaustion: () => 0,
  });

  assert.equal(result, "ready");
  assert.equal(attempts, 4);
});
