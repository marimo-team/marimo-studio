import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.resolve("vite-plus/package.json"));
const { parse } = require("yaml");
const picomatch = require("picomatch");
const workflow = async (name) =>
  parse(await readFile(new URL(`../../workflows/${name}.yml`, import.meta.url), "utf8"));

test("frontend test failure survives timing-log capture", async () => {
  const ci = await workflow("ci");
  const step = ci.jobs.frontend.steps.find((step) => step.name === "Test frontend");
  const directory = await mkdtemp(join(tmpdir(), "frontend-workflow-results-"));
  try {
    await writeFile(join(directory, "make"), '#!/bin/sh\nprintf "test failed\\n"\nexit 23\n', {
      mode: 0o755,
    });
    // GitHub's explicit bash template enables pipefail. Its default shell does not.
    const flags = step.shell === "bash" ? ["-e", "-o", "pipefail"] : ["-e"];
    const result = spawnSync("bash", [...flags, "-c", step.run], {
      env: {
        ...process.env,
        PATH: `${directory}${delimiter}${process.env.PATH}`,
        RUNNER_TEMP: directory,
      },
      encoding: "utf8",
    });
    assert.equal(result.status, 23, result.stderr);
    assert.equal(await readFile(join(directory, "frontend-tests.log"), "utf8"), "test failed\n");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("browser result uploads include offset-owned report directories", async () => {
  const browser = await workflow("e2e");
  const uploads = Object.values(browser.jobs)
    .flatMap((job) => job.steps ?? [])
    .filter((step) => step.with?.name?.startsWith("browser-results-"));
  assert.ok(uploads.length > 0);
  for (const upload of uploads) {
    const matches = picomatch(upload.with.path);
    for (const path of [
      "apps/e2e/test-results/blob-main/offset-100/main-linux-100.zip",
      "apps/e2e/test-results/blob-provider/offset-0/provider-linux.zip",
      "apps/e2e/test-results/blob-installed/offset-0/installed-windows.zip",
    ]) {
      assert.ok(matches(path), `${upload.with.name} must include ${path}`);
    }
  }
});

test("browser consumers receive the producer's prepared Python payload", async () => {
  const browser = await workflow("e2e");
  const producer = browser.jobs["browser-assets"].steps.find(
    (step) =>
      step.uses?.startsWith("actions/upload-artifact@") && step.with?.name === "browser-pyodide",
  );
  assert.equal(producer.with.path, "apps/e2e/.cache/pyodide");
  for (const name of [
    "e2e",
    "package-e2e",
    "windows-e2e",
    "windows-provider-e2e",
    "windows-installed-e2e",
  ]) {
    const consumer = browser.jobs[name].steps.find(
      (step) =>
        step.uses?.startsWith("actions/download-artifact@") &&
        step.with?.name === producer.with.name,
    );
    assert.ok(consumer, `${name} requires the prepared Python payload`);
    assert.equal(consumer.with.path, "apps/e2e/.cache/pyodide", name);
  }
});
