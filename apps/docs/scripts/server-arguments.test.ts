import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "vite-plus/test";

import { documentationServerArguments } from "./server-arguments.ts";

const root = fileURLToPath(new URL("..", import.meta.url));

test.each(["dev", "preview"])(
  "%s uses the assigned port through the native VitePress CLI",
  (mode) => {
    expect(documentationServerArguments([mode], "4826")).toEqual([
      mode,
      "--host",
      "127.0.0.1",
      "--port",
      "4826",
      "--strictPort",
    ]);
  },
);

test.each([undefined, "4321suffix"])("rejects a missing or malformed assigned port %s", (port) => {
  expect(() => documentationServerArguments(["preview"], port)).toThrow(
    "PORT must be assigned by Portless; run pnpm dev or pnpm preview.",
  );
});

test.each(["0", "65536"])("rejects an assigned port outside the TCP range %s", (port) => {
  expect(() => documentationServerArguments(["preview"], port)).toThrow(RangeError);
});

test("server commands cannot override Portless's assigned port", () => {
  expect(() => documentationServerArguments(["dev", "--port", "4321"], "4826")).toThrow(
    "documentation",
  );
});

test("raw preview rejects missing PORT before loading or serving the build", () => {
  const env = { ...process.env };
  delete env.PORT;
  const result = spawnSync(process.execPath, ["scripts/serve-docs.ts", "preview"], {
    cwd: root,
    env,
    encoding: "utf8",
    timeout: 10_000,
  });
  expect(result.status).toBe(1);
  expect(result.stderr).toContain("PORT must be assigned by Portless");
});

test("dev and preview run separately named Portless servers", () => {
  const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  const previewName = /--name (\S+)/.exec(manifest.scripts.preview)?.[1];
  expect(manifest.scripts.dev).toBe("portless");
  expect(previewName).toBeDefined();
  expect(previewName).not.toBe(manifest.portless.name);
  expect(manifest.scripts[manifest.portless.script]).toContain("scripts/serve-docs.ts dev");
  expect(manifest.scripts.preview).toMatch(/^portless run .*\bpreview:server$/);
  expect(manifest.scripts["preview:server"]).toContain("scripts/serve-docs.ts preview");
});
