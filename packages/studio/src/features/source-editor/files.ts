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

export const sourceRecord = <Value>(
  create: (name: SourceName) => Value,
): Record<SourceName, Value> => {
  const result = {} as Record<SourceName, Value>;
  for (const name of SOURCE_NAMES) {
    result[name] = create(name);
  }
  return result;
};

const SOURCE_TAB_MOVES: Readonly<Record<string, (index: number) => number>> = {
  ArrowLeft: (index) => (index - 1 + SOURCE_FILES.length) % SOURCE_FILES.length,
  ArrowRight: (index) => (index + 1) % SOURCE_FILES.length,
  End: () => SOURCE_FILES.length - 1,
  Home: () => 0,
};

export const sourceTabForKey = (current: SourceName, key: string): SourceName | undefined => {
  const move = SOURCE_TAB_MOVES[key];
  const index = SOURCE_NAMES.indexOf(current);
  if (!move || index < 0) {
    return undefined;
  }
  return SOURCE_NAMES[move(index)];
};
