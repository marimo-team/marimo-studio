import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const metadataPath = join(packageRoot, ".cache", "source.json");

export const marimoSourceSchema = z.object({
  commit: z.string().min(1),
  path: z.string().min(1),
  repository: z.string().min(1),
  version: z.string().min(1),
});

const marimoSourceCodec = z.codec(z.string(), marimoSourceSchema, {
  decode: (source, context) => {
    try {
      return JSON.parse(source);
    } catch (error) {
      context.issues.push({
        code: "invalid_format",
        format: "json",
        input: source,
        message: error instanceof Error ? error.message : "Invalid JSON",
      });
      return z.NEVER;
    }
  },
  encode: (metadata) => JSON.stringify(metadata),
});

export const decodeMarimoSource = (source) => marimoSourceCodec.decode(source);
export const readMarimoSource = async () =>
  decodeMarimoSource(await readFile(metadataPath, "utf8"));
export const readMarimoSourceSync = () => decodeMarimoSource(readFileSync(metadataPath, "utf8"));
