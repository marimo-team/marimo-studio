import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { notifyProjectionChanged, subscribeProjectionChanges } from "../src/projections/changes.ts";

test("projection changes coalesce before subscribers rescan the document", async () => {
  let changes = 0;
  const unsubscribe = subscribeProjectionChanges(() => {
    changes += 1;
  });

  notifyProjectionChanged();
  notifyProjectionChanged();
  notifyProjectionChanged();
  assert.equal(changes, 0);

  await Promise.resolve();
  assert.equal(changes, 1);

  notifyProjectionChanged();
  unsubscribe();
  await Promise.resolve();
  assert.equal(changes, 1);
});
