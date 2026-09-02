import { resolve, sep } from "node:path";
import { expect, test } from "vite-plus/test";

import { createE2ENetwork, createMainShardPortOffsets } from "../scripts/network.mjs";
import { createE2EPaths } from "../scripts/paths.mjs";

test("offsets every E2E endpoint without creating collisions", () => {
  const defaults = createE2ENetwork();
  const offset = createE2ENetwork("100");

  expect(defaults.portOffset).toBe(0);
  expect(offset.portOffset).toBe(100);
  for (const [baselineScope, movedScope] of [
    [defaults.main, offset.main],
    [defaults.provider, offset.provider],
  ]) {
    expect(new Set(Object.keys(movedScope))).toEqual(new Set(Object.keys(baselineScope)));
    const baselineEndpoints = Object.values(baselineScope);
    const movedEndpoints = Object.values(movedScope);
    for (const [index, baseline] of baselineEndpoints.entries()) {
      const moved = movedEndpoints[index];
      expect(moved).toBeDefined();
      if (moved === undefined) throw new Error("Offset endpoint is unavailable");
      expect(moved.port).toBe(baseline.port + 100);
      expect(moved.origin).toBe(`http://127.0.0.1:${moved.port}`);
    }
  }
  const ports = [...Object.values(defaults.main), ...Object.values(defaults.provider)].map(
    ({ port }) => port,
  );
  expect(new Set(ports).size).toBe(ports.length);
});

test("isolates mutable paths across suites and concurrent runs", () => {
  const root = resolve("/repo/apps/e2e");
  const defaults = createE2EPaths(root);
  const offset = createE2EPaths(root, 100);

  expect(defaults.providerPlaywrightOutputDirectory).not.toBe(
    defaults.mainPlaywrightOutputDirectory,
  );
  expect(defaults.providerPlaywrightReportDirectory).not.toBe(
    defaults.mainPlaywrightReportDirectory,
  );
  expect(new Set(Object.values(offset)).size).toBe(Object.values(offset).length);
  const offsetRoot = resolve(root, "test-results/offset-100") + sep;
  expect(Object.values(offset).every((path) => path.includes(offsetRoot))).toBe(true);
});

test("bounds E2E port offsets to valid TCP ports", () => {
  expect(() => createE2ENetwork("-1")).toThrow(TypeError);
  expect(() => createE2ENetwork("61200")).toThrow(RangeError);
  const highest = createE2ENetwork("61199");
  expect(
    [...Object.values(highest.main), ...Object.values(highest.provider)].every(
      ({ port }) => port <= 65_535,
    ),
  ).toBe(true);
});

test("adds main shard isolation to the caller's port offset", () => {
  expect(createMainShardPortOffsets()).toEqual([100, 200, 300]);
  expect(createMainShardPortOffsets("1000")).toEqual([1_100, 1_200, 1_300]);
  expect(createMainShardPortOffsets("60899")).toEqual([60_999, 61_099, 61_199]);
  expect(() => createMainShardPortOffsets("60900")).toThrow(RangeError);
});
