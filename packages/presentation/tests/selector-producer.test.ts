import { expect, test } from "vite-plus/test";

import { selectorProducerCell } from "../src/projections/resolution.ts";
import { projectionRequest, projectionRuntimeConfig } from "./runtime-fixtures.ts";

test("a value selector's producer is the runtime cell that defines its root", () => {
  const config = projectionRuntimeConfig([projectionRequest('chart.axes[0]["title"]', "output")]);

  expect(selectorProducerCell(config, 'chart.axes[0]["title"]')).toBe("chart-cell");
  expect(selectorProducerCell(config, "chart")).toBe("chart-cell");
  expect(selectorProducerCell(config, "missing.figure")).toBeUndefined();
  expect(selectorProducerCell(config, "chart._private")).toBeUndefined();
});
