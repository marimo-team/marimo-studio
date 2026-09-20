import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { createE2ENetwork } from "../scripts/network.mjs";
import { startRoutedNotebookProcess } from "../scripts/routed-notebook-process.mjs";
import { stopNotebookProcess } from "../scripts/server-process.mjs";

test("failed supervisor startup settles routed readiness without unhandled rejection", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "studio-routed-failure-"));
  const network = createE2ENetwork({ runId: "startup-failure", suite: "unit", workerId: "one" });
  let unhandled = 0;
  const observe = () => {
    unhandled += 1;
  };
  process.on("unhandledRejection", observe);
  await network.start();
  const service = startRoutedNotebookProcess({
    endpoint: network.main.studio,
    command: process.execPath,
    args: ["-e", ""],
    cwd: resolve(root, "missing"),
    directory: resolve(root, "registry"),
    env: process.env,
  });
  try {
    await expect(service.ready).rejects.toThrow("process group ID");
    await stopNotebookProcess(service, { shutdown: "process", timeout: 1000 });
    await new Promise<void>((done) => setImmediate(done));
    expect(unhandled).toBe(0);
    expect(service.child.pid).toBeUndefined();
  } finally {
    process.off("unhandledRejection", observe);
    await network.close();
    await rm(root, { recursive: true, force: true });
  }
});
