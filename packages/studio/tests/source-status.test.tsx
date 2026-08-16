import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import type { SourceState } from "../src/features/source-editor/sync.ts";

import { useSourceStatus } from "../src/features/source-editor/useSourceStatus.ts";

interface SourceStatusProps {
  state: SourceState;
}

describe("source status", () => {
  afterEach(() => vi.useRealTimers());

  test("derives current source state while settling each external update", async () => {
    vi.useFakeTimers();
    const first = { name: "index.html", phase: "external" } satisfies SourceState;
    const initialProps: SourceStatusProps = { state: first };
    const { result, rerender } = renderHook(
      ({ state }: SourceStatusProps) => useSourceStatus(state),
      { initialProps },
    );

    expect(result.current).toEqual({ message: "Updated from disk", phase: "external" });
    await act(() => vi.advanceTimersByTimeAsync(1_800));
    expect(result.current).toEqual({ message: "Saved ✓", phase: "saved" });

    const second = { name: "index.html", phase: "external" } satisfies SourceState;
    rerender({ state: second });
    expect(result.current).toEqual({ message: "Updated from disk", phase: "external" });

    rerender({
      state: { name: "index.html", phase: "error", message: "Could not read source" },
    });
    expect(result.current).toEqual({ message: "Could not read source", phase: "error" });
  });
});
