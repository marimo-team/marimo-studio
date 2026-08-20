import { readFile, unlink, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const packageRoot = dirname(fileURLToPath(import.meta.url));
const outputRoot = resolve(
  packageRoot,
  "../../packages/marimo-studio/src/marimo_studio/_static/browser",
);
const runtimePath = join(outputRoot, "entry-closures.runtime.json");
const zeroPythonPath = join(outputRoot, "entry-closures.zero-python.json");
const outputPath = join(outputRoot, "entry-closures.json");

const entrySchema = z
  .object({
    script: z.string().min(1),
    styles: z.array(z.string().min(1)),
    assets: z.array(z.string().min(1)),
  })
  .strict();
const partialClosureSchema = z
  .object({
    schema: z.literal(1),
    entries: z.record(z.string(), entrySchema),
  })
  .strict();

const readClosure = async (path, entry) => {
  const parsed = partialClosureSchema.parse(JSON.parse(await readFile(path, "utf8")));
  if (Object.keys(parsed.entries).length !== 1 || parsed.entries[entry] === undefined) {
    throw new Error(`Browser entry closure ${JSON.stringify(entry)} is invalid.`);
  }
  return parsed.entries[entry];
};

const [runtime, zeroPython] = await Promise.all([
  readClosure(runtimePath, "runtime"),
  readClosure(zeroPythonPath, "zero-python"),
]);
await writeFile(
  outputPath,
  `${JSON.stringify(
    {
      schema: 1,
      entries: { runtime, "zero-python": zeroPython },
    },
    null,
    2,
  )}\n`,
  "utf8",
);
await Promise.all([unlink(runtimePath), unlink(zeroPythonPath)]);
