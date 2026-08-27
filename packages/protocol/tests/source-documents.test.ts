import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import type { JsonValue } from "../src/runtime-config.ts";

import {
  artifactPublicPathSchema,
  sourceDocumentPathSchema,
  sourceDocumentSchema,
} from "../src/source-documents.ts";
import { parseViewProject } from "../src/view-project.ts";
import { unbuiltView } from "./fixtures.ts";

const projectPayload = () => ({
  schema: 1 as const,
  view: "react",
  provider: "marimo-studio/react",
  provider_options: {
    entrypoint: "src/App.tsx",
    compiler: { jsx: true, targets: ["chrome", 120, null] },
  },
  documents: [
    { path: "src/App.tsx", language: "typescriptreact", access: "edit" as const },
    { path: "src/theme.css", language: "css", access: "edit" as const },
    { path: "deno.lock", language: "json", access: "read" as const },
  ],
  mounts: [],
  diagnostics: [],
  build: unbuiltView,
  artifact: null,
});

test("source documents accept provider languages, nested paths, and access modes", () => {
  assert.deepEqual(
    sourceDocumentSchema.parse({
      path: "src/components/MetricCard.svelte",
      language: "svelte",
      access: "edit",
      label: "Metric card",
    }),
    {
      path: "src/components/MetricCard.svelte",
      language: "svelte",
      access: "edit",
      label: "Metric card",
    },
  );
  assert.equal(
    sourceDocumentSchema.parse({ path: "deno.lock", language: "json", access: "read" }).access,
    "read",
  );
});

test("source document paths reject paths outside the view project", () => {
  for (const path of [
    "",
    "/src/App.tsx",
    "../App.tsx",
    "src/../App.tsx",
    "src\\App.tsx",
    "C:/src/App.tsx",
    "c:src/App.tsx",
    "src/cafe\u0301.tsx",
    ".ARTIFACTS/development.json",
  ]) {
    assert.equal(sourceDocumentPathSchema.safeParse(path).success, false, path);
  }
});

test("artifact public paths allow artifacts while rejecting unsafe routes", () => {
  for (const path of ["artifacts/index.html", "assets/app.js", "index.html"]) {
    assert.equal(artifactPublicPathSchema.safeParse(path).success, true, path);
  }
  for (const path of [
    "",
    "/index.html",
    "../index.html",
    "assets/../index.html",
    "assets\\index.html",
    "C:/index.html",
    "assets/index\u007f.html",
    "assets/cafe\u0301.html",
    "_MARIMO-STUDIO/runtime.js",
    "@file/data.csv",
    "public/app.js",
    "PUBLIC-FILES-SW.JS",
  ]) {
    assert.equal(artifactPublicPathSchema.safeParse(path).success, false, path);
  }
});

test("view projects accept ordered provider document catalogs with unique paths", () => {
  const project = projectPayload();

  assert.deepEqual(
    JSON.parse(JSON.stringify(parseViewProject(project).provider_options)),
    project.provider_options,
  );
  assert.deepEqual(
    parseViewProject(project).documents.map(({ path }) => path),
    ["src/App.tsx", "src/theme.css", "deno.lock"],
  );
  assert.deepEqual(parseViewProject({ ...project, documents: [] }).documents, []);
  assert.throws(() =>
    parseViewProject({
      ...project,
      documents: [project.documents[0], project.documents[0]],
    }),
  );
});

test("view projects reject unknown fields and non-namespaced provider identities", () => {
  assert.throws(() => parseViewProject({ ...projectPayload(), unexpected: true }));
  assert.throws(() => parseViewProject({ ...projectPayload(), provider: "react" }));
  assert.throws(() =>
    parseViewProject({ ...projectPayload(), provider_options: { compiler: Number.NaN } }),
  );
});

test("view projects preserve prototype-named provider options as own records", () => {
  const nested: Record<string, JsonValue> = Object.fromEntries([["__proto__", { enabled: true }]]);
  const entries: [string, JsonValue][] = [
    ["__proto__", { nested: [null, true, 7, 1.25, "label"] }],
    ["constructor", { enabled: false, nested }],
  ];
  const providerOptions = Object.fromEntries(entries);
  const parsed = parseViewProject({ ...projectPayload(), provider_options: providerOptions });

  assert.equal(Object.getPrototypeOf(parsed.provider_options), null);
  assert.equal(Object.hasOwn(parsed.provider_options, "__proto__"), true);
  assert.deepEqual(
    JSON.parse(JSON.stringify(parsed.provider_options["__proto__"])),
    providerOptions["__proto__"],
  );
  assert.equal(Object.hasOwn(parsed.provider_options, "constructor"), true);
  const constructor = Object(parsed.provider_options["constructor"]);
  assert.equal(Object.getPrototypeOf(constructor), null);
  const decodedNested = Object(constructor["nested"]);
  assert.equal(Object.getPrototypeOf(decodedNested), null);
  assert.equal(Object.hasOwn(decodedNested, "__proto__"), true);
});

test("view projects require unique sites tied to declared source documents", () => {
  const site = {
    id: "site-app",
    kind: "cell" as const,
    source: { path: "src/App.tsx", line: 1, column: 1 },
    allowedTargets: ["chart"],
  };
  assert.equal(parseViewProject({ ...projectPayload(), mounts: [site] }).mounts.length, 1);
  assert.throws(() => parseViewProject({ ...projectPayload(), mounts: [site, site] }));
  assert.throws(() =>
    parseViewProject({
      ...projectPayload(),
      mounts: [{ ...site, source: { path: "src/Hidden.tsx", line: 1, column: 1 } }],
    }),
  );
  assert.throws(() =>
    parseViewProject({
      ...projectPayload(),
      mounts: [{ ...site, source: { path: "src/../App.tsx", line: 1, column: 1 } }],
    }),
  );
});

test("view projects expose compact publication identity", () => {
  const artifact = {
    profile: "development" as const,
    input_id: "sha256:project",
    artifact_id: "sha256:artifact",
  };
  const project = {
    ...projectPayload(),
    build: {
      ...unbuiltView,
      phase: "published" as const,
      project_revision: artifact.input_id,
      artifact_revision: artifact.artifact_id,
    },
    artifact,
  };

  const retained = parseViewProject({
    ...project,
    provider: "marimo-studio/svelte",
    provider_options: { entrypoint: "src/App.svelte", compiler: null },
    documents: [{ path: "src/App.svelte", language: "svelte", access: "edit" }],
    mounts: [],
    diagnostics: [
      {
        code: "build-failed",
        severity: "error",
        message: "The current Svelte source failed to build.",
        hint: "Repair src/App.svelte.",
        source: { path: "src/App.svelte", line: 1, column: 1 },
      },
    ],
  });

  assert.equal(retained.artifact?.input_id, "sha256:project");
  assert.equal(retained.artifact?.artifact_id, "sha256:artifact");
  assert.throws(() =>
    parseViewProject({
      ...project,
      artifact: { profile: "development", input_id: "sha256:project" },
    }),
  );
});

test("view projects reject malformed persisted diagnostics", () => {
  const diagnostic = {
    code: "source-invalid",
    severity: "error" as const,
    message: "Source is invalid.",
    hint: "Repair the source.",
    source: { path: "src/App.tsx", line: 1, column: 1 },
  };
  const malformed = [
    { ...diagnostic, code: "INVALID" },
    { ...diagnostic, severity: "info" },
    { ...diagnostic, message: " Source is invalid. " },
    { ...diagnostic, hint: " Repair the source. " },
    { ...diagnostic, source: { ...diagnostic.source, path: ".ARTIFACTS/build.json" } },
    { ...diagnostic, source: { ...diagnostic.source, line: 0 } },
  ];

  malformed.forEach((item) =>
    assert.throws(() => parseViewProject({ ...projectPayload(), diagnostics: [item] })),
  );
});

test("view projects accept manifest diagnostics without exposing the manifest", () => {
  const diagnostic = {
    code: "provider-options-invalid",
    severity: "error" as const,
    message: "The provider options are invalid.",
    hint: "Repair view.toml.",
    source: { path: "view.toml", line: 1, column: 1 },
  };
  const payload = projectPayload();
  const parsed = parseViewProject({
    ...payload,
    diagnostics: [diagnostic],
    build: { ...payload.build, phase: "failed", diagnostics: [diagnostic] },
  });

  assert.deepEqual(parsed.documents, payload.documents);
  assert.equal(parsed.diagnostics[0]?.source?.path, "view.toml");
  assert.equal(parsed.build.diagnostics[0]?.source?.path, "view.toml");
  const undeclared = {
    ...diagnostic,
    source: { ...diagnostic.source, path: "src/Hidden.tsx" },
  };
  assert.throws(() => parseViewProject({ ...payload, diagnostics: [undeclared] }));
  assert.throws(() =>
    parseViewProject({
      ...payload,
      build: { ...payload.build, diagnostics: [undeclared] },
    }),
  );
});
