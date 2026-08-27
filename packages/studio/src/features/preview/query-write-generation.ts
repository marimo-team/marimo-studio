const WRITE_GENERATION_KEY = "__marimoStudioQueryWriteGeneration__";

type QueryGenerationGlobal = typeof globalThis & {
  [WRITE_GENERATION_KEY]?: number;
};

export const nextQueryWriteGeneration = (): number => {
  // SAFETY: This module is the sole writer and stores finite number generations.
  const page = globalThis as QueryGenerationGlobal;
  const previous = page[WRITE_GENERATION_KEY] ?? -1;
  const generation = Math.max(Date.now(), previous + 1);
  page[WRITE_GENERATION_KEY] = generation;
  return generation;
};
