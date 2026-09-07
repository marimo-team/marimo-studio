import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { preparePyodidePayload, verifyPyodidePayload } from "../scripts/prepare-pyodide.mjs";
import { installPinnedPyodideAssets } from "../tests/pyodide-assets.ts";

const roots: string[] = [];

const fixture = async () => {
  const root = await mkdtemp(join(tmpdir(), "studio-pyodide-payload-"));
  roots.push(root);
  const source = join(root, "upstream/node_modules/pyodide");
  const destination = join(root, "browser-artifact/pyodide");
  await mkdir(source, { recursive: true });
  const files = {
    "package.json": JSON.stringify({ name: "pyodide", version: "314.0.0" }),
    "pyodide.mjs": "export const version = '314.0.0';\n",
    "pyodide.js": "exports.version = '314.0.0';\n",
    "pyodide.asm.mjs": "export default async () => ({});\n",
    "pyodide.asm.wasm": Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]),
    "python_stdlib.zip": Buffer.concat([Buffer.from([80, 75, 5, 6]), Buffer.alloc(18)]),
    "pyodide-lock.json": JSON.stringify({ info: { version: "314.0.0" }, packages: {} }),
  };
  for (const [name, content] of Object.entries(files)) await writeFile(join(source, name), content);
  return { root, source, destination };
};

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

test("a prepared runtime verifies after the upstream source is deleted", async () => {
  const { root, source, destination } = await fixture();
  await preparePyodidePayload(source, destination);
  await rm(join(root, "upstream"), { recursive: true });

  const payload = await verifyPyodidePayload(destination);

  expect(payload.manifest.version).toBe("314.0.0");
  expect(await readFile(join(payload.directory, "pyodide.asm.wasm"))).toEqual(
    Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]),
  );
  expect(payload.manifest.files["pyodide.asm.wasm"].bytes).toBe(8);
});

test("browser routing serves the transferred payload after its producer source is deleted", async () => {
  const { root, source, destination } = await fixture();
  await preparePyodidePayload(source, destination);
  await rm(join(root, "upstream"), { recursive: true });
  const context = {
    route: vi.fn<Parameters<typeof installPinnedPyodideAssets>[0]["route"]>(async () => ({
      dispose: async () => {},
      [Symbol.asyncDispose]: async () => {},
    })),
  };
  await installPinnedPyodideAssets(context, destination);
  expect(context.route.mock.calls[0]?.[0]).toBe(
    "https://cdn.jsdelivr.net/pyodide/v314.0.0/full/**",
  );
  const handler = context.route.mock.calls[0]![1];
  const route = {
    fulfill: vi.fn(async () => {}),
    continue: vi.fn(async () => {}),
  };
  await handler(route, {
    url: () => "https://cdn.jsdelivr.net/pyodide/v314.0.0/full/pyodide.asm.wasm",
  });
  expect(route.fulfill).toHaveBeenCalledWith({
    path: join(destination, "pyodide.asm.wasm"),
    contentType: "application/wasm",
  });
  expect(route.continue).not.toHaveBeenCalled();
  expect(await readFile(join(destination, "pyodide.asm.wasm"))).toEqual(
    Buffer.from([0, 97, 115, 109, 1, 0, 0, 0]),
  );
});

test("preparation rejects a different upstream Pyodide version", async () => {
  const { source, destination } = await fixture();
  await writeFile(
    join(source, "package.json"),
    JSON.stringify({ name: "pyodide", version: "0.29.0" }),
  );

  await expect(preparePyodidePayload(source, destination)).rejects.toThrow();
});

test("runtime verification rejects changed or missing asset bytes", async () => {
  const { source, destination } = await fixture();
  await preparePyodidePayload(source, destination);
  await writeFile(
    join(destination, "pyodide.asm.wasm"),
    Buffer.from([0, 97, 115, 109, 1, 0, 0, 1]),
  );
  await expect(verifyPyodidePayload(destination)).rejects.toThrow(
    "integrity mismatch: pyodide.asm.wasm",
  );

  await preparePyodidePayload(source, destination);
  await rm(join(destination, "python_stdlib.zip"));
  await expect(verifyPyodidePayload(destination)).rejects.toThrow("python_stdlib.zip");
});
