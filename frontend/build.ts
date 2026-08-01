import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { run } from "./command.ts";
import {
  marimoRepository,
  marimoVersionFromUvLock,
  prepareMarimo,
} from "./marimo-source.ts";

interface HtmxSource {
  path: string;
  version: string;
}

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const resolveHtmx = async (): Promise<HtmxSource> => {
  const path = fileURLToPath(import.meta.resolve("htmx.org"));
  const manifest: unknown = JSON.parse(
    await Deno.readTextFile(join(dirname(path), "..", "package.json")),
  );
  if (!isRecord(manifest) || typeof manifest.version !== "string") {
    throw new Error("The resolved htmx.org package must declare a version");
  }
  return { path, version: manifest.version };
};

const build = async (): Promise<void> => {
  const marimoVersion = marimoVersionFromUvLock(
    await Deno.readTextFile(join(root, "uv.lock")),
  );
  const marimo = await prepareMarimo(marimoVersion);
  const htmx = await resolveHtmx();
  await run(
    "node",
    [join(here, "build-vite.mjs"), root, marimo.path, htmx.path],
    root,
  );

  const output = join(
    root,
    "src",
    "marimo_studio",
    "_static",
    "server-runtime",
  );
  await Deno.copyFile(
    join(here, "src", "studio.css"),
    join(output, "studio.css"),
  );
  const styleSource = join(here, "src", "studio", "styles");
  const styleOutput = join(output, "studio", "styles");
  await Deno.mkdir(styleOutput, { recursive: true });
  for await (const entry of Deno.readDir(styleSource)) {
    if (entry.isFile && entry.name.endsWith(".css")) {
      await Deno.copyFile(
        join(styleSource, entry.name),
        join(styleOutput, entry.name),
      );
    }
  }
  await Deno.writeTextFile(
    join(output, "build-meta.json"),
    JSON.stringify(
      {
        marimo: {
          repository: marimoRepository,
          version: marimoVersion,
          commit: marimo.commit,
        },
        htmx: {
          version: htmx.version,
        },
      },
      null,
      2,
    ) + "\n",
  );
};

if (import.meta.main) {
  await build();
}
