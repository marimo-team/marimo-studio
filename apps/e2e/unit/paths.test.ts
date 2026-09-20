import { isAbsolute, resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import type { E2ENetworkIdentity } from "../scripts/network.ts";

import { appDirectory, createE2EPaths } from "../scripts/paths.ts";

test("isolates workspaces and reports across runs, suites, and restarted workers", () => {
  const root = appDirectory;
  const identities: E2ENetworkIdentity[] = [
    { runId: "run-a", suite: "main", workerId: "0" },
    { runId: "run-b", suite: "main", workerId: "0" },
    { runId: "run-a", suite: "provider", workerId: "0" },
    { runId: "run-a", suite: "main", workerId: "1" },
    { runId: "run-a", suite: "installed", workerId: "controller" },
  ];
  const outputs = identities.map((identity) => createE2EPaths(root, identity));
  const paths = outputs.flatMap(Object.values);
  expect(paths.every(isAbsolute)).toBe(true);
  expect(new Set(paths).size).toBe(paths.length);
  expect(outputs[0]!.notebookProcessRegistryDirectory).toBe(
    resolve(root, "test-results/run-a/main/0/workspace/.notebook-processes"),
  );
  expect(outputs[0]!.blobReportDirectory).toBe(resolve(root, "test-results/blob-main/run-a/0"));
});
