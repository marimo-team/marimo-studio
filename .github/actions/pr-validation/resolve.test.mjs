import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const actionDirectory = dirname(fileURLToPath(import.meta.url));
const resolver = resolve(actionDirectory, "resolve.sh");
const mergedTree = "a".repeat(40);
const headSha = "b".repeat(40);

const pull = (overrides = {}) => ({
  number: 7,
  merged_at: "2026-09-05T00:00:00Z",
  merge_commit_sha: "c".repeat(40),
  base: { ref: "main" },
  head: {
    label: "marimo-team:topic",
    ref: "topic",
    sha: headSha,
    repo: { full_name: "marimo-team/marimo-studio" },
  },
  ...overrides,
});

const workflowRun = (overrides = {}) => ({
  id: 91,
  status: "completed",
  conclusion: "success",
  created_at: "2026-09-05T00:00:00Z",
  run_attempt: 1,
  head_branch: "topic",
  head_repository: { full_name: "marimo-team/marimo-studio" },
  html_url: "https://example.test/run/91",
  ...overrides,
});

const fakeCommand = async (directory, name, source) => {
  const path = join(directory, name);
  await writeFile(path, source, "utf8");
  await chmod(path, 0o755);
};

const runResolver = async (overrides = {}) => {
  const directory = await mkdtemp(join(tmpdir(), "pr-validation-test-"));
  const output = join(directory, "output");
  const summary = join(directory, "summary");
  await fakeCommand(
    directory,
    "gh",
    `#!/usr/bin/env node
const args = process.argv.slice(2).join(" ");
if (process.env.FAIL_API && args.includes(process.env.FAIL_API)) process.exit(1);
let value;
if (args.includes("/commits/") && args.endsWith("/pulls")) value = process.env.PULLS_JSON;
else if (args.includes("/pulls") && args.includes("state=all")) value = process.env.HEAD_PULLS_JSON;
else if (args.includes("/actions/workflows/") && args.includes("event=push")) value = process.env.BASE_RUNS_JSON;
else if (args.includes("/actions/workflows/")) value = process.env.RUNS_JSON;
else if (args.includes("/actions/runs/") && args.endsWith("/artifacts")) value = process.env.ARTIFACTS_JSON;
else if (args.includes("/actions/artifacts/") && args.endsWith("/zip")) value = "archive";
else process.exit(2);
process.stdout.write(value ?? "");
`,
  );
  await fakeCommand(
    directory,
    "git",
    `#!/usr/bin/env node
process.stdout.write(process.env.MERGED_TREE + "\\n");
`,
  );
  await fakeCommand(
    directory,
    "unzip",
    `#!/usr/bin/env node
process.stdout.write(process.env.TESTED_TREE + "\\n");
`,
  );

  const selectedPull = pull();
  const environment = {
    ...process.env,
    PATH: `${directory}:${process.env.PATH}`,
    GITHUB_EVENT_NAME: "push",
    GITHUB_OUTPUT: output,
    GITHUB_REF: "refs/heads/main",
    GITHUB_REF_NAME: "main",
    GITHUB_REPOSITORY: "marimo-team/marimo-studio",
    GITHUB_SHA: selectedPull.merge_commit_sha,
    GITHUB_STEP_SUMMARY: summary,
    VALIDATION_WORKFLOW: "e2e.yml",
    PULLS_JSON: JSON.stringify([selectedPull]),
    HEAD_PULLS_JSON: JSON.stringify([selectedPull]),
    RUNS_JSON: JSON.stringify({ workflow_runs: [workflowRun()] }),
    BASE_RUNS_JSON: JSON.stringify({
      workflow_runs: [workflowRun({ head_branch: "main" })],
    }),
    ARTIFACTS_JSON: JSON.stringify({
      artifacts: [{ id: 12, name: "pr-validation-tree", expired: false, size_in_bytes: 41 }],
    }),
    MERGED_TREE: mergedTree,
    TESTED_TREE: mergedTree,
    ...overrides,
  };
  const result = spawnSync("bash", [resolver], { encoding: "utf8", env: environment });
  const validation = await readFile(output, "utf8");
  const explanation = await readFile(summary, "utf8");
  await rm(directory, { force: true, recursive: true });
  assert.equal(result.status, 0, result.stderr);
  return { explanation, validation };
};

test("reuses a successful run whose tested tree matches main", async () => {
  const result = await runResolver();
  assert.equal(result.validation, "validated=true\n");
  assert.match(result.explanation, /passed e2e\.yml for Git tree/);
});

test("pull request events publish evidence without reusing it", async () => {
  const result = await runResolver({ GITHUB_EVENT_NAME: "pull_request", FAIL_API: "api" });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /pull request run owns validation/);
});

test("a different tested tree falls back to main validation", async () => {
  const result = await runResolver({ TESTED_TREE: "d".repeat(40) });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /tested a different Git tree/);
});

test("a failed latest run falls back to main validation", async () => {
  const result = await runResolver({
    RUNS_JSON: JSON.stringify({ workflow_runs: [workflowRun({ conclusion: "failure" })] }),
  });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /no successful e2e\.yml run/);
});

test("a failed previous main run forces complete validation", async () => {
  const result = await runResolver({
    BASE_RUNS_JSON: JSON.stringify({
      workflow_runs: [workflowRun({ head_branch: "main", conclusion: "failure" })],
    }),
  });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /previous main commit has no successful e2e\.yml run/);
});

test("duplicate head ownership falls back to main validation", async () => {
  const selected = pull();
  const result = await runResolver({
    HEAD_PULLS_JSON: JSON.stringify([selected, pull({ number: 8 })]),
  });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /does not uniquely own its head commit/);
});

test("fork pull requests fall back to main validation", async () => {
  const fork = pull({
    head: {
      label: "contributor:topic",
      ref: "topic",
      sha: headSha,
      repo: { full_name: "contributor/marimo-studio" },
    },
  });
  const result = await runResolver({ PULLS_JSON: JSON.stringify([fork]) });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /comes from another repository/);
});

test("missing artifacts fall back to main validation", async () => {
  const result = await runResolver({ ARTIFACTS_JSON: JSON.stringify({ artifacts: [] }) });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /no unique tested-tree artifact/);
});

test("GitHub API failures fall back to main validation", async () => {
  const result = await runResolver({ FAIL_API: "event=pull_request" });
  assert.equal(result.validation, "validated=false\n");
  assert.match(result.explanation, /workflow evidence could not be read/);
});
