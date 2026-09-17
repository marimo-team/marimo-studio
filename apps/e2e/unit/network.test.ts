import { resolve, sep } from "node:path";
import { expect, test } from "vite-plus/test";

import { createE2ENetwork, workerPortOffset } from "../scripts/network.mjs";
import { createE2EPaths } from "../scripts/paths.mjs";

const baseNetwork = createE2ENetwork();
const maximumOffset =
  65_535 -
  Math.max(
    ...Object.values(baseNetwork.main).map(({ port }) => port),
    ...Object.values(baseNetwork.provider).map(({ port }) => port),
  );

test("offsets every E2E endpoint without creating collisions", () => {
  const offset = createE2ENetwork("100");

  expect(baseNetwork.portOffset).toBe(0);
  expect(offset.portOffset).toBe(100);
  for (const [baselineScope, movedScope] of [
    [baseNetwork.main, offset.main],
    [baseNetwork.provider, offset.provider],
  ]) {
    expect(new Set(Object.keys(movedScope))).toEqual(new Set(Object.keys(baselineScope)));
    for (const [name, baseline] of Object.entries(baselineScope)) {
      expect(movedScope).toHaveProperty(name, {
        port: baseline.port + 100,
        origin: `http://127.0.0.1:${baseline.port + 100}`,
      });
    }
  }
  const ports = [...Object.values(baseNetwork.main), ...Object.values(baseNetwork.provider)].map(
    ({ port }) => port,
  );
  expect(new Set(ports).size).toBe(ports.length);
});

test("isolates mutable paths across suites and concurrent runs", () => {
  const root = resolve("/repo/apps/e2e");
  const defaults = createE2EPaths(root);
  const offset = createE2EPaths(root, 100);

  expect(defaults.providerWorkspaceDirectory).not.toBe(defaults.workspaceDirectory);
  expect(defaults.hostedWorkspaceDirectory).not.toBe(defaults.workspaceDirectory);
  expect(new Set(Object.values(offset)).size).toBe(Object.values(offset).length);
  const offsetRoot = resolve(root, "test-results/main/offset-100") + sep;
  expect(Object.values(offset).every((path) => path.includes(offsetRoot))).toBe(true);
});

test("main and provider workers own separate mutable roots at the same offset", () => {
  const root = resolve("/repo/apps/e2e");
  const main = createE2EPaths(root, 100, "main");
  const provider = createE2EPaths(root, 100, "provider");
  const mainRoot = resolve(root, "test-results/main/offset-100") + sep;
  const providerRoot = resolve(root, "test-results/provider/offset-100") + sep;

  expect(Object.values(main).every((path) => path.startsWith(mainRoot))).toBe(true);
  expect(Object.values(provider).every((path) => path.startsWith(providerRoot))).toBe(true);
  expect(main.notebookProcessRegistryDirectory).not.toBe(provider.notebookProcessRegistryDirectory);
});

test("bounds E2E port offsets to valid TCP ports", () => {
  expect(() => createE2ENetwork("-1")).toThrow(TypeError);
  expect(() => createE2ENetwork(String(maximumOffset + 1))).toThrow(RangeError);
  const highest = createE2ENetwork(String(maximumOffset));
  expect(
    [...Object.values(highest.main), ...Object.values(highest.provider)].every(
      ({ port }) => port <= 65_535,
    ),
  ).toBe(true);
});

test("isolates restarted workers above the caller's port offset", () => {
  expect(workerPortOffset()).toBe(0);
  expect(workerPortOffset("1000", "0")).toBe(1_100);
  expect(workerPortOffset("1000", "1")).toBe(1_200);
  expect(workerPortOffset("1000", "2")).toBe(1_300);
  expect(workerPortOffset(String(maximumOffset - 300), "2")).toBe(maximumOffset);
  expect(() => workerPortOffset(String(maximumOffset - 299), "2")).toThrow(RangeError);
});
