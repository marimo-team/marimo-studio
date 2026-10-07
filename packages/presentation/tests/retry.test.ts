import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { boundedRetryAfterExhaustion, retry } from "../src/retry.ts";

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

test("a bounded exhaustion schedule stops a permanently transient state", async () => {
  let attempts = 0;
  const afterExhaustion = boundedRetryAfterExhaustion([0, 0], () => true);

  await assert.rejects(
    retry({
      operation: () => {
        attempts += 1;
        return Promise.reject(new Error("pending"));
      },
      delays: [0],
      retryWhen: () => true,
      retryAfterExhaustion: afterExhaustion,
    }),
    { message: "pending" },
  );

  assert.equal(attempts, 4);
});
