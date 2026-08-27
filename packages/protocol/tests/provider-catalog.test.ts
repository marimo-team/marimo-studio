import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { starterSchema } from "../src/provider-catalog.ts";
import { starter } from "./fixtures.ts";

test("starter records expose creation choices without provider internals", () => {
  assert.deepEqual(starterSchema.parse(starter), starter);
  assert.throws(() => starterSchema.parse({ ...starter, id: "Invalid starter" }));
  assert.throws(() => starterSchema.parse({ ...starter, documents: ["index.html", "index.html"] }));
});
