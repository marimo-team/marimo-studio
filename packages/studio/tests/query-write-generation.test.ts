import { afterEach, expect, it, vi } from "vite-plus/test";

afterEach(() => {
  vi.restoreAllMocks();
});

it("retains monotonic write generations across module recreation", async () => {
  vi.spyOn(Date, "now").mockReturnValue(1_000);
  vi.resetModules();
  const first = await import("../src/features/preview/query-write-generation.ts");
  const firstGeneration = first.nextQueryWriteGeneration();

  vi.resetModules();
  const recreated = await import("../src/features/preview/query-write-generation.ts");
  const nextGeneration = recreated.nextQueryWriteGeneration();

  expect(nextGeneration).toBe(firstGeneration + 1);
});
