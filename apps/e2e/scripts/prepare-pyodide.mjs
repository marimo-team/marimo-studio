import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import { appDirectory } from "./paths.mjs";

export const PYODIDE_VERSION = "314.0.0";
export const PYODIDE_CDN_ROOT = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
export const pyodidePayloadDirectory = resolve(appDirectory, ".cache/pyodide");

const runtimeFiles = [
  "package.json",
  "pyodide.mjs",
  "pyodide.js",
  "pyodide.asm.mjs",
  "pyodide.asm.wasm",
  "python_stdlib.zip",
  "pyodide-lock.json",
];
const packageSchema = z.object({ name: z.literal("pyodide"), version: z.literal(PYODIDE_VERSION) });
const manifestSchema = z
  .object({
    schema: z.literal(1),
    version: z.literal(PYODIDE_VERSION),
    files: z.record(
      z.string(),
      z
        .object({
          bytes: z.number().int().positive(),
          sha256: z.string().regex(/^[a-f\d]{64}$/),
        })
        .strict(),
    ),
  })
  .strict();
const digest = (content) => createHash("sha256").update(content).digest("hex");

export const verifyPyodidePayload = async (directory) => {
  const manifest = manifestSchema.parse(
    JSON.parse(await readFile(join(directory, "manifest.json"), "utf8")),
  );
  const names = Object.keys(manifest.files);
  if (names.length !== runtimeFiles.length || names.some((name) => !runtimeFiles.includes(name))) {
    throw new Error("Prepared Pyodide runtime has an incomplete file inventory");
  }
  packageSchema.parse(JSON.parse(await readFile(join(directory, "package.json"), "utf8")));
  for (const name of runtimeFiles) {
    const content = await readFile(join(directory, name));
    const expected = manifest.files[name];
    if (content.byteLength !== expected.bytes || digest(content) !== expected.sha256) {
      throw new Error(`Prepared Pyodide runtime integrity mismatch: ${name}`);
    }
  }
  return Object.freeze({ directory, files: Object.freeze(names), manifest });
};

export const preparePyodidePayload = async (source, destination) => {
  packageSchema.parse(JSON.parse(await readFile(join(source, "package.json"), "utf8")));
  const contents = await Promise.all(
    runtimeFiles.map(async (name) => {
      const content = await readFile(join(source, name));
      if (content.byteLength === 0) throw new Error(`Pyodide runtime file is empty: ${name}`);
      return [name, content];
    }),
  );
  const manifest = {
    schema: 1,
    version: PYODIDE_VERSION,
    files: Object.fromEntries(
      contents.map(([name, content]) => [
        name,
        {
          bytes: content.byteLength,
          sha256: digest(content),
        },
      ]),
    ),
  };
  const current = await verifyPyodidePayload(destination).catch(() => undefined);
  if (current && JSON.stringify(current.manifest) === JSON.stringify(manifest)) return current;
  await mkdir(dirname(destination), { recursive: true });
  const staging = `${destination}.staging-${randomUUID()}`;
  await mkdir(staging);
  try {
    for (const [name, content] of contents) await writeFile(join(staging, name), content);
    await writeFile(join(staging, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
    await verifyPyodidePayload(staging);
    await rm(destination, { force: true, recursive: true });
    await rename(staging, destination);
  } finally {
    await rm(staging, { force: true, recursive: true });
  }
  return verifyPyodidePayload(destination);
};

const preparedPyodideSource = async () => {
  const { readMarimoSource } =
    await import("../../../packages/marimo-frontend/scripts/metadata.mjs");
  const source = await readMarimoSource();
  const require = createRequire(join(source.path, "frontend/package.json"));
  return dirname(require.resolve("pyodide/package.json"));
};

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  await preparePyodidePayload(await preparedPyodideSource(), pyodidePayloadDirectory);
  process.stdout.write(`Prepared Pyodide ${PYODIDE_VERSION} browser test assets\n`);
}
