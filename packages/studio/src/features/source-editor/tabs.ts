import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";

export const sourceTabForKey = (
  paths: readonly SourceDocumentPath[],
  current: SourceDocumentPath,
  key: string,
): SourceDocumentPath | undefined => {
  const index = paths.indexOf(current);
  if (index < 0 || paths.length === 0) {
    return undefined;
  }
  switch (key) {
    case "ArrowLeft":
      return paths[(index - 1 + paths.length) % paths.length];
    case "ArrowRight":
      return paths[(index + 1) % paths.length];
    case "End":
      return paths.at(-1);
    case "Home":
      return paths[0];
    default:
      return undefined;
  }
};
