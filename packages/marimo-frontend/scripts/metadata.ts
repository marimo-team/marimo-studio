import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";

const metadataPath = join(import.meta.dirname, "..", ".cache", "source.json");

const marimoSourceSchema = z.object({
  commit: z.string().min(1),
  patchSha256: z.string().regex(/^[\da-f]{64}$/u),
  path: z.string().min(1),
  repository: z.string().min(1),
  version: z.string().min(1),
});

export type MarimoSource = z.infer<typeof marimoSourceSchema>;

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

export const decodeMarimoSource = (source: string): MarimoSource =>
  marimoSourceCodec.decode(source);
export const readMarimoSource = async (): Promise<MarimoSource> =>
  decodeMarimoSource(await readFile(metadataPath, "utf8"));
export const readMarimoSourceSync = (): MarimoSource =>
  decodeMarimoSource(readFileSync(metadataPath, "utf8"));
