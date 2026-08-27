import { expect, test } from "vite-plus/test";

import { resolveProjection } from "../src/projections/resolution.ts";
import { groupValueProjections } from "../src/runtime/values/value-groups.ts";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures.ts";

test("value groups belong to the projection revision that resolved their hosts", () => {
  const request = projectionRequest("metric", "value");
  const config = projectionRuntimeConfig([request]);
  const resolution = resolveProjection(config, request);
  if (!resolution.ok) {
    throw new Error(resolution.error.message);
  }
  const projections = [
    {
      host: document.createElement("strong"),
      projection: resolution.value,
      request,
      projectionRevision: "revision-1",
    },
  ];

  expect(groupValueProjections(projections, "revision-2")).toEqual([]);
  expect(groupValueProjections(projections, "revision-1")).toEqual([
    {
      key: "cell:v1:metric",
      projections: [request],
      runtimeCellId: "metric-cell",
      selectors: ["metric"],
    },
  ]);
});
