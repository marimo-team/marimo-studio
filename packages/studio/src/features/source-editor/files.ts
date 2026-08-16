import { sourceNameSchema, type SourceName } from "@marimo-studio/protocol/source-events";

export interface SourceFile {
  id: string;
  language: "css" | "html";
  name: SourceName;
}

const SOURCE_METADATA = {
  "index.html": { id: "html", language: "html" },
  "app.css": { id: "css", language: "css" },
} as const satisfies Record<SourceName, Omit<SourceFile, "name">>;

export const SOURCE_NAMES: readonly SourceName[] = sourceNameSchema.options;

export const SOURCE_FILES: readonly SourceFile[] = SOURCE_NAMES.map((name) => ({
  name,
  ...SOURCE_METADATA[name],
}));

export const sourceRecord = <Value>(create: (name: SourceName) => Value) =>
  ({
    "index.html": create("index.html"),
    "app.css": create("app.css"),
  }) satisfies Record<SourceName, Value>;

export const sourceTabForKey = (current: SourceName, key: string): SourceName | undefined => {
  const index = SOURCE_NAMES.indexOf(current);
  if (index < 0) {
    return undefined;
  }
  switch (key) {
    case "ArrowLeft":
      return SOURCE_NAMES[(index - 1 + SOURCE_FILES.length) % SOURCE_FILES.length];
    case "ArrowRight":
      return SOURCE_NAMES[(index + 1) % SOURCE_FILES.length];
    case "End":
      return SOURCE_NAMES.at(-1);
    case "Home":
      return SOURCE_NAMES[0];
    default:
      return undefined;
  }
};
