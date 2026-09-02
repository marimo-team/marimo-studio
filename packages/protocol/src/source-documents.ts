import { z } from "zod";

const isNormalizedRelativePath = (value: string): boolean => {
  let hasControlCharacter = false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 32 || (code >= 127 && code <= 159)) {
      hasControlCharacter = true;
      break;
    }
  }
  if (!value || value.startsWith("/") || value.includes("\\") || hasControlCharacter) {
    return false;
  }
  if (/^[A-Za-z]:/.test(value) || value.normalize("NFC") !== value) {
    return false;
  }
  const parts = value.split("/");
  return parts.every((part) => part !== "" && part !== "." && part !== "..");
};

const isRelativeDocumentPath = (value: string): boolean =>
  isNormalizedRelativePath(value) && value.split("/")[0]?.toLowerCase() !== ".artifacts";

const reservedArtifactRoots = new Set(["_marimo-studio", "@file", "public", "public-files-sw.js"]);

const isArtifactPublicPath = (value: string): boolean =>
  isNormalizedRelativePath(value) &&
  !reservedArtifactRoots.has(value.split("/")[0]?.toLowerCase() ?? "");

export const sourceDocumentPathSchema = z
  .string()
  .refine(isRelativeDocumentPath, "Source document paths must be normalized relative POSIX paths");

export const artifactPublicPathSchema = z
  .string()
  .refine(
    isArtifactPublicPath,
    "Artifact public paths must be normalized relative POSIX paths outside reserved routes",
  );

export const sourceDocumentSchema = z
  .object({
    path: sourceDocumentPathSchema,
    language: z.string().trim().min(1),
    access: z.enum(["edit", "read"]),
    label: z.string().trim().min(1).nullable().optional(),
  })
  .strict();

export type SourceDocumentPath = z.infer<typeof sourceDocumentPathSchema>;
export type ArtifactPublicPath = z.infer<typeof artifactPublicPathSchema>;
export type SourceDocument = z.infer<typeof sourceDocumentSchema>;
