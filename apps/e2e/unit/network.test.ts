import { expect, test } from "vite-plus/test";

import { createE2ENetwork } from "../scripts/network.mjs";
import { createE2EPaths } from "../scripts/paths.mjs";

test("offsets every E2E endpoint while preserving the default port map", () => {
  const defaults = createE2ENetwork();
  const offset = createE2ENetwork("100");

  expect(defaults.portOffset).toBe(0);
  expect(offset.portOffset).toBe(100);

  expect(Object.values(defaults.main).map(({ port }) => port)).toEqual([
    4_321, 4_322, 4_323, 4_324, 4_325, 4_326,
  ]);
  expect(Object.values(defaults.provider).map(({ port }) => port)).toEqual([
    4_331, 4_332, 4_333, 4_334,
  ]);
  expect(offset.main.studio).toEqual({ origin: "http://127.0.0.1:4421", port: 4_421 });
  expect(offset.provider.external).toEqual({ origin: "http://127.0.0.1:4434", port: 4_434 });
});

test("isolates every mutable path while preserving default CI locations", () => {
  const defaults = createE2EPaths("/repo/apps/e2e");
  const offset = createE2EPaths("/repo/apps/e2e", 100);

  expect(defaults.workspaceDirectory).toBe("/repo/apps/e2e/.workspace");
  expect(defaults.configDirectory).toBe("/repo/apps/e2e/test-results/xdg-config");
  expect(defaults.mainPlaywrightOutputDirectory).toBe("/repo/apps/e2e/test-results");
  expect(defaults.mainPlaywrightReportDirectory).toBe("/repo/apps/e2e/playwright-report");
  expect(new Set(Object.values(offset)).size).toBe(Object.values(offset).length);
  expect(Object.values(offset).every((path) => path.includes("/test-results/offset-100/"))).toBe(
    true,
  );
});

test("rejects invalid E2E port offsets before starting a server", () => {
  for (const source of ["", "-1", "1.5", "invalid"]) {
    expect(() => createE2ENetwork(source)).toThrow("must be a non-negative integer");
  }
  expect(() => createE2ENetwork("61202")).toThrow("must be between 0 and 61201");
});
