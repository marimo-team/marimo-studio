import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import picomatch from "picomatch";
import { test } from "vite-plus/test";
import { parse } from "yaml";

interface Step {
  readonly name?: string;
  readonly run?: string;
  readonly shell?: string;
  readonly uses?: string;
  readonly with?: Readonly<Record<string, string>>;
}

interface Job {
  readonly needs?: string | readonly string[];
  readonly steps?: readonly Step[];
  readonly strategy?: { readonly matrix: Readonly<Record<string, readonly string[]>> };
}

interface Workflow {
  readonly jobs: Readonly<Record<string, Job>>;
}

const workflow = async (name: string): Promise<Workflow> =>
  parse(await readFile(new URL(`../../workflows/${name}.yml`, import.meta.url), "utf8"));
const steps = (job: Job | undefined): readonly Step[] => job?.steps ?? [];
const artifactStep = (job: Job | undefined, action: string, name: string): Step | undefined =>
  steps(job).find((step) => step.uses?.startsWith(`${action}@`) && step.with?.name === name);

test("frontend test failure survives timing-log capture", async () => {
  const ci = await workflow("ci");
  const step = steps(ci.jobs.frontend).find((step) => step.name === "Test frontend");
  assert.ok(step?.run);
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

test("browser result uploads include run and worker report directories", async () => {
  for (const name of ["e2e", "platforms"]) {
    const browser = await workflow(name);
    const uploads = Object.values(browser.jobs)
      .flatMap(steps)
      .filter((step) => step.with?.name?.startsWith("browser-results-"));
    assert.ok(uploads.length > 0, name);
    for (const upload of uploads) {
      const { name: artifact, path: pattern } = upload.with ?? {};
      assert.ok(pattern, artifact);
      const matches = picomatch(pattern);
      for (const path of [
        "apps/e2e/test-results/blob-main/run-a/controller/main-linux-1.zip",
        "apps/e2e/test-results/blob-provider/run-b/controller/provider-linux.zip",
        "apps/e2e/test-results/blob-installed/run-c/controller/installed-windows.zip",
      ]) {
        assert.ok(matches(path), `${artifact} must include ${path}`);
      }
    }
  }
});

test("browser consumers receive the producer's prepared Python payload", async () => {
  for (const [name, producerJob, consumers] of [
    ["e2e", "browser-assets", ["e2e", "package-e2e"]],
    ["platforms", "artifacts", ["windows-e2e", "windows-provider-e2e", "windows-installed-e2e"]],
  ] as const) {
    const browser = await workflow(name);
    const producer = artifactStep(
      browser.jobs[producerJob],
      "actions/upload-artifact",
      "browser-pyodide",
    );
    assert.equal(producer?.with?.path, "apps/e2e/.cache/pyodide");
    for (const job of consumers) {
      const consumer = artifactStep(
        browser.jobs[job],
        "actions/download-artifact",
        "browser-pyodide",
      );
      assert.ok(consumer, `${job} requires the prepared Python payload`);
      assert.equal(consumer.with?.path, "apps/e2e/.cache/pyodide", job);
    }
  }
});

test("platform consumers install the one package candidate the workflow builds", async () => {
  const platforms = await workflow("platforms");
  const builds = Object.entries(platforms.jobs).filter(([, job]) =>
    steps(job).some((step) => step.run?.includes("make _package-build")),
  );
  assert.deepEqual(
    builds.map(([name]) => name),
    ["artifacts"],
  );
  for (const job of ["installed-package", "windows-installed-e2e"]) {
    const download = artifactStep(
      platforms.jobs[job],
      "actions/download-artifact",
      "package-candidate",
    );
    assert.ok(download, `${job} installs the package candidate`);
    assert.ok(platforms.jobs[job]?.needs?.includes("artifacts"), job);
  }
});

test("the site exports every documentation example family", async () => {
  const pages = await workflow("pages");
  const { documentationExampleFamilies } = await import("../../../apps/docs/examples.ts");
  assert.deepEqual(
    [...(pages.jobs.examples?.strategy?.matrix.family ?? [])].sort(),
    documentationExampleFamilies.map((family) => family.slug).sort(),
  );
});

test("preview publication waits for every workflow the release checks require", async () => {
  const read = (path: string) => readFile(new URL(`../../../${path}`, import.meta.url), "utf8");
  const publish = parse(await read(".github/workflows/publish.yml"));
  const triggers: readonly string[] = publish.on.workflow_run.workflows;
  const checks = await read("scripts/require-release-checks.sh");
  const files = [...checks.matchAll(/^\s*"[^"|]+\|([\w.-]+\.yml)"$/gm)].map((match) => match[1]);
  const names: readonly string[] = await Promise.all(
    files.map(async (file) => parse(await read(`.github/workflows/${file}`)).name),
  );
  assert.deepEqual(triggers.toSorted(), names.toSorted());
});
