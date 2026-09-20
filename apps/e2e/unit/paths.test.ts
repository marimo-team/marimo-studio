import { isAbsolute, resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { createE2EPaths } from "../scripts/paths.mjs";

test("isolates workspaces and reports across runs, suites, and restarted workers", () => {
  const root = resolve("apps/e2e");
  const identities = [
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
