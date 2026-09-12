import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { appDirectory, repositoryDirectory } from "../scripts/paths.mjs";

const launcher = resolve(appDirectory, "scripts/_compat/marimo_edit.py");

const configurePort = (offset: number, installedVersion = "0.24.2") =>
  spawnSync(
    "uv",
    [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "python",
      "-c",
      [
        "import runpy",
        `launcher = runpy.run_path(${JSON.stringify(launcher)})`,
        `print(launcher["configure_lsp_port"](${offset}, ${JSON.stringify(installedVersion)}))`,
      ].join("; "),
    ],
    {
      cwd: repositoryDirectory,
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
    },
  );

test("moves Marimo's pinned LSP range by the E2E port offset", () => {
  const result = configurePort(1300);

  expect(result.status, result.stderr).toBe(0);
  expect(result.stdout.trim()).toBe("4018");
});

test("rejects a different pinned Marimo version", () => {
  const result = configurePort(0, "0.25.0");

  expect(result.status).not.toBe(0);
  expect(result.stderr).toContain("expected version 0.24.2, found 0.25.0");
});

test("rejects an E2E offset beyond the LSP port range", () => {
  const result = configurePort(62_818);

  expect(result.status).not.toBe(0);
  expect(result.stderr).toContain("E2E Marimo LSP port must not exceed 65535");
});

test("forwards Marimo's port option without treating it as a launcher option", () => {
  const result = spawnSync(
    "uv",
    [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "python",
      launcher,
      "--port-offset",
      "1300",
      "--port",
      "4321",
      "--help",
    ],
    { cwd: repositoryDirectory, encoding: "utf8", maxBuffer: 1024 * 1024 },
  );

  expect(result.status, result.stderr).toBe(0);
  expect(result.stdout).toContain("--port INTEGER");
});
