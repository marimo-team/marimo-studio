import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { promisify } from "node:util";
import { expect, test } from "vite-plus/test";

import { withExportRepository } from "../scripts/export-repository.mjs";

const exec = promisify(execFile);

test("worker subprocesses inherit repository ownership until failed work settles", async () => {
  const previous = process.env.MARIMO_EXPORT_REPOSITORY;
  const repository = resolve("worker", "export-repository");
  const failure = new Error("export failed");
  await expect(
    withExportRepository(repository, async () => {
      const { stdout } = await exec(process.execPath, [
        "-e",
        "process.stdout.write(process.env.MARIMO_EXPORT_REPOSITORY)",
      ]);
      expect(stdout).toBe(repository);
      throw failure;
    }),
  ).rejects.toBe(failure);
  expect(process.env.MARIMO_EXPORT_REPOSITORY).toBe(previous);
});
