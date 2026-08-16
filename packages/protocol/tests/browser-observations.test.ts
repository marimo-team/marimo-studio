import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "vite-plus/test";
import { z } from "zod";

import { browserObservationSchema } from "../src/browser-observations.ts";
import { jsonValueSchema } from "../src/runtime-config.ts";

const invalidCasesSchema = z.array(
  z.object({
    name: z.string(),
    patch: z.record(z.string(), jsonValueSchema),
  }),
);

const fixture = JSON.parse(
  readFileSync(new URL("../fixtures/browser-observation.json", import.meta.url), "utf8"),
);
const invalidCases = invalidCasesSchema.parse(
  JSON.parse(
    readFileSync(new URL("../fixtures/browser-observation-invalid.json", import.meta.url), "utf8"),
  ),
);

test("browser observation fixtures satisfy the strict protocol", () => {
  assert.deepEqual(browserObservationSchema.parse(fixture), fixture);
  assert.equal(browserObservationSchema.safeParse({ ...fixture, extra: true }).success, false);
});

test("browser observation fixtures reject invalid protocol values", () => {
  for (const invalid of invalidCases) {
    assert.equal(
      browserObservationSchema.safeParse({ ...fixture, ...invalid.patch }).success,
      false,
      invalid.name,
    );
  }
});
