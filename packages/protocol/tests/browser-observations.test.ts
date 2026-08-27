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

test("browser observations reject contradictory projection evidence", () => {
  const readyWithFailedProjection = structuredClone(fixture);
  readyWithFailedProjection.state = "ready";
  readyWithFailedProjection.diagnostics = [];
  readyWithFailedProjection.runtimeStatus.current = {
    phase: "ready",
    diagnostics: [],
  };
  readyWithFailedProjection.runtimeStatus.transitions = [
    {
      sequence: 1,
      observedAt: 1_100,
      revision: "revision-1",
      sessionId: "s_123456",
      phase: "ready",
      diagnostics: [],
      diagnosticsTruncated: false,
    },
  ];
  assert.equal(browserObservationSchema.safeParse(readyWithFailedProjection).success, false);

  const missingError = structuredClone(fixture);
  missingError.projectionInstances[0].error = null;
  assert.equal(browserObservationSchema.safeParse(missingError).success, false);
});

test("browser observations retain compact mount failure evidence", () => {
  const emptyTarget = structuredClone(fixture);
  emptyTarget.projectionInstances[0].target = "";
  emptyTarget.projectionInstances[0].error.code = "projection-target-empty";
  assert.equal(browserObservationSchema.safeParse(emptyTarget).success, true);

  const oversizedTarget = structuredClone(fixture);
  oversizedTarget.projectionInstances[0].target = `summary.${"x".repeat(4_096)}`;
  oversizedTarget.projectionInstances[0].error.code = "projection-target-too-large";
  assert.equal(browserObservationSchema.safeParse(oversizedTarget).success, true);

  const overflow = structuredClone(fixture);
  overflow.projectionInstances = Array.from({ length: 513 }, (_, index) => ({
    ...structuredClone(fixture.projectionInstances[0]),
    instanceId: `projection-${index}`,
  }));
  overflow.projectionInstances.at(-1).error.code = "projection-instance-limit";
  assert.equal(browserObservationSchema.safeParse(overflow).success, true);

  overflow.projectionInstances.push({
    ...structuredClone(fixture.projectionInstances[0]),
    instanceId: "projection-513",
  });
  assert.equal(browserObservationSchema.safeParse(overflow).success, false);
});
