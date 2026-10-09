import { readFile, unlink, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { z } from "zod";

import type { BrowserEntryClosure, BrowserEntryClosures } from "../entry-closures.ts";

const outputRoot = resolve(
  import.meta.dirname,
  "../../../packages/marimo-studio/src/marimo_studio/_static/browser",
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

const readClosure = async (path: string, entry: string): Promise<BrowserEntryClosure> => {
  const parsed = partialClosureSchema.parse(JSON.parse(await readFile(path, "utf8")));
  const closure = parsed.entries[entry];
  if (Object.keys(parsed.entries).length !== 1 || closure === undefined) {
    throw new Error(`Browser entry closure ${JSON.stringify(entry)} is invalid.`);
  }
  return closure;
};

const [runtime, zeroPython] = await Promise.all([
  readClosure(runtimePath, "runtime"),
  readClosure(zeroPythonPath, "zero-python"),
]);
const closures: BrowserEntryClosures = {
  schema: 1,
  entries: { runtime, "zero-python": zeroPython },
};
await writeFile(outputPath, `${JSON.stringify(closures, null, 2)}\n`, "utf8");
await Promise.all([unlink(runtimePath), unlink(zeroPythonPath)]);
