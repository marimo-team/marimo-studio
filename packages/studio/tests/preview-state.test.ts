import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { previewLoadState, RetrySchedule } from "../src/features/preview/state.ts";

test("preview loads distinguish startup waits from repair failures", () => {
  assert.deepEqual(
    previewLoadState({ hasRuntimeRoot: false, documentState: "waiting" }),
    "waiting",
  );
  assert.deepEqual(previewLoadState({ hasRuntimeRoot: true, documentState: "waiting" }), "ready");
  assert.deepEqual(previewLoadState({ hasRuntimeRoot: false }), "error");
});

test("preview retries back off and reset after the receiver connects", () => {
  const schedule = new RetrySchedule([10, 20]);

  assert.deepEqual([schedule.next(), schedule.next(), schedule.next()], [10, 20, 20]);
  schedule.reset();
  assert.deepEqual(schedule.next(), 10);
});
