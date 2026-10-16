import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { transformWithOxc } from "vite";
import { onTestFinished } from "vite-plus/test";

export const lineEndingVariants = (source: string) => [source, source.replaceAll("\n", "\r\n")];

let importedModules = 0;

// Node caches data modules by URL, so each import gets a distinct URL and
// evaluates with the current bindings.
export const importModule = async (source: string) => {
  importedModules += 1;
  const unique = `${source}\n// module ${importedModules}\n`;
  return import(`data:text/javascript;base64,${Buffer.from(unique).toString("base64")}`);
};

const bindingsKey = "__marimoStudioTransformedModuleBindings";

// Data modules cannot resolve bare or virtual specifiers, so named imports
// read their bindings from a test-owned global instead.
export const importModuleWithBindings = async <Bindings extends object>(
  source: string,
  bindings: Bindings,
) => {
  Reflect.set(globalThis, bindingsKey, bindings);
  onTestFinished(() => {
    Reflect.deleteProperty(globalThis, bindingsKey);
  });
  return importModule(
    source.replaceAll(
      /import\s*\{([^}]*)\}\s*from\s*"[^"]+";/gu,
      `const {$1} = globalThis.${bindingsKey};`,
    ),
  );
};

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
