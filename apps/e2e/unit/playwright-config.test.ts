import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { afterEach, expect, test, vi } from "vite-plus/test";

const exec = promisify(execFile);

afterEach(() => vi.unstubAllEnvs());

test.each([
  ["playwright.config.ts", "main", undefined],
  ["playwright.config.ts", "main", "0"],
  ["playwright.providers.config.ts", "provider", "1"],
])("%s keeps the %s network unstarted for worker %s", async (config, suite, workerId) => {
  const parentRunId = "parent-run";
  vi.stubEnv("MARIMO_STUDIO_E2E_RUN_ID", parentRunId);
  const environment = { ...process.env };
  if (workerId === undefined) delete environment.TEST_WORKER_INDEX;
  else environment.TEST_WORKER_INDEX = workerId;
  delete environment.MARIMO_STUDIO_E2E_RUN_ID;
  delete environment.MARIMO_STUDIO_E2E_SUITE;
  const configUrl = new URL(`../${config}`, import.meta.url).href;
  const networkUrl = new URL("../scripts/network.ts", import.meta.url).href;
  const { stdout } = await exec(
    process.execPath,
    [
      "--input-type=module",
      "-e",
      `
        await import(${JSON.stringify(configUrl)});
        const { e2eNetwork } = await import(${JSON.stringify(networkUrl)});
        try {
          let running = false;
          try { running = new URL(e2eNetwork.main.studio.origin).port !== ""; } catch {}
          console.log(JSON.stringify({
            running,
            suite: e2eNetwork.suite,
            workerId: e2eNetwork.workerId,
            runId: e2eNetwork.runId,
            childEnvironmentRunId: process.env.MARIMO_STUDIO_E2E_RUN_ID,
          }));
        } finally {
          await e2eNetwork.close();
        }
      `,
    ],
    { env: environment, timeout: 10_000 },
  );
  const result = JSON.parse(stdout);
  expect(result.runId).not.toBe(parentRunId);
  expect(result).toEqual({
    running: false,
    suite,
    workerId: workerId ?? "controller",
    runId: expect.any(String),
    childEnvironmentRunId: result.runId,
  });
});
