import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.resolve("vite-plus/package.json"));
const { parse } = require("yaml");
const picomatch = require("picomatch");
const filters = parse(await readFile(new URL("../../filters.yml", import.meta.url), "utf8"));
const names = [
  "main_browser",
  "provider_browser",
  "installed_browser",
  "windows_lifecycle",
  "windows_unit",
];

// paths-filter applies picomatch with dotfiles and the some-with-excludes predicate.
const selected = (path) =>
  names.filter((name) => {
    const patterns = filters[name].flat(Infinity);
    return picomatch(
      patterns.filter((pattern) => !pattern.startsWith("!")),
      {
        dot: true,
        ignore: patterns
          .filter((pattern) => pattern.startsWith("!"))
          .map((pattern) => pattern.slice(1)),
      },
    )(path);
  });

test("main workspace changes select live browser and Windows lifecycle acceptance", () => {
  assert.deepEqual(selected("apps/e2e/scripts/main-workspace.ts"), [
    "main_browser",
    "windows_lifecycle",
    "windows_unit",
  ]);
});

test("provider workspace changes select provider browser acceptance", () => {
  assert.deepEqual(selected("apps/e2e/scripts/provider-workspace.ts"), [
    "provider_browser",
    "windows_unit",
  ]);
  assert.deepEqual(selected("apps/e2e/tests/provider-fixture.ts"), [
    "provider_browser",
    "windows_unit",
  ]);
});

test("export repository isolation selects every workspace consumer", () => {
  assert.deepEqual(selected("apps/e2e/scripts/export-repository.ts"), [
    "main_browser",
    "provider_browser",
    "windows_lifecycle",
    "windows_unit",
  ]);
});

test("notebook service ownership selects every server consumer", () => {
  for (const path of [
    "apps/e2e/scripts/notebook-services.ts",
    "apps/e2e/scripts/notebook-process-supervisor.ts",
    "apps/e2e/scripts/_compat/server.py",
    "apps/e2e/scripts/_compat/endpoint.py",
  ]) {
    assert.deepEqual(
      selected(path),
      [
        "main_browser",
        "provider_browser",
        "installed_browser",
        "windows_lifecycle",
        "windows_unit",
      ],
      path,
    );
  }
});

test("shared browser diagnostics select installed acceptance as well", () => {
  assert.deepEqual(selected("apps/e2e/tests/browser-diagnostics.ts"), [
    "main_browser",
    "provider_browser",
    "installed_browser",
    "windows_lifecycle",
    "windows_unit",
  ]);
});

test("prepared Python assets select every browser consumer", () => {
  assert.deepEqual(selected("apps/e2e/scripts/prepare-pyodide.ts"), [
    "main_browser",
    "provider_browser",
    "installed_browser",
    "windows_lifecycle",
    "windows_unit",
  ]);
});

test("Notebook Kit spec changes select their owning provider suite", () => {
  assert.deepEqual(selected("apps/e2e/tests/provider-notebook.spec.ts"), ["provider_browser"]);
});

test("provider preview spec changes select their owning provider suite", () => {
  assert.deepEqual(selected("apps/e2e/tests/provider-preview.spec.ts"), ["provider_browser"]);
});

const matches = (name, path) => {
  const patterns = filters[name].flat(Infinity);
  return picomatch(
    patterns.filter((pattern) => !pattern.startsWith("!")),
    {
      dot: true,
      ignore: patterns
        .filter((pattern) => pattern.startsWith("!"))
        .map((pattern) => pattern.slice(1)),
    },
  )(path);
};

test("process, filesystem, and dependency changes run platform contracts on the pull request", () => {
  for (const path of [
    "packages/marimo-studio/src/marimo_studio/_filesystem/_windows.py",
    "packages/marimo-studio/src/marimo_studio/_processes/provider_runner.py",
    "packages/marimo-studio/src/marimo_studio/view_providers/_host/registry.py",
    "packages/marimo-studio/src/marimo_studio/view_providers/_bundled/_deno/runtime.py",
    "uv.lock",
    "pnpm-lock.yaml",
    ".github/workflows/platforms.yml",
    "apps/e2e/scripts/process-group.ts",
  ]) {
    assert.equal(matches("platform_sensitive", path), true, path);
  }
});

test("portable product changes defer platform contracts until after merge", () => {
  for (const path of [
    "packages/marimo-studio/src/marimo_studio/_projections/resolution.py",
    "packages/marimo-studio/src/marimo_studio/view_providers/_bundled/deno_react/build.py",
    "packages/presentation/src/runtime/wasm.ts",
    "docs/guide/views.md",
  ]) {
    assert.equal(matches("platform_sensitive", path), false, path);
  }
});

test("documentation and example changes build the complete site on the pull request", () => {
  for (const path of [
    "docs/guide/views.md",
    "apps/docs/examples.ts",
    "examples/athletes.py",
    "examples/__marimo__/studio/athletes/overview/index.html",
    ".github/workflows/pages.yml",
  ]) {
    assert.equal(matches("docs_site", path), true, path);
  }
  assert.equal(
    matches("docs_site", "packages/marimo-studio/src/marimo_studio/_projections/resolution.py"),
    false,
  );
  assert.equal(
    matches("pages", "packages/marimo-studio/src/marimo_studio/_projections/resolution.py"),
    true,
  );
});
