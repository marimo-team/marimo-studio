import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { transformWithOxc } from "vite";
import { onTestFinished } from "vite-plus/test";

export const lineEndingVariants = (source: string) => [source, source.replaceAll("\n", "\r\n")];

export const importModule = async (source: string) =>
  import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const compileTypeScript = async (source: string, loader = "ts") => {
  const transformed = await transformWithOxc(source, `fixture.${loader}`, {
    jsx: { pragma: "createElement", runtime: "classic" },
  });
  return transformed.code;
};

export const importTypeScriptModule = async (source: string, loader = "ts") =>
  importModule(await compileTypeScript(source, loader));

export const temporaryDirectory = async (prefix: string) => {
  const path = await mkdtemp(join(tmpdir(), prefix));
  onTestFinished(() =>
    rm(path, {
      force: true,
      maxRetries: 10,
      recursive: true,
      retryDelay: 20,
    }),
  );
  return path;
};

export const importTypeScriptFile = async (source: string) => {
  const directory = await temporaryDirectory("marimo-studio-transformed-module-");
  const path = join(directory, "fixture.mjs");
  await writeFile(path, await compileTypeScript(source));
  return import(pathToFileURL(path).href);
};
