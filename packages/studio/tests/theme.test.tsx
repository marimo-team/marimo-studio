import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi } from "vite-plus/test";

import type { StudioTheme, ThemeFrameConnector } from "../src/theme.tsx";

import { useResolvedStudioTheme } from "../src/theme.tsx";

describe("Studio theme", () => {
  test("follows the native editor theme and disconnects with the shell", () => {
    let publish: ((theme: StudioTheme | undefined) => void) | undefined;
    const disconnect = vi.fn();
    const connect: ThemeFrameConnector = (_frame, listener) => {
      publish = listener;
      return disconnect;
    };
    const frame = document.createElement("iframe");
    const { result, unmount } = renderHook(() => useResolvedStudioTheme(frame, connect));

    expect(result.current).toBe("light");
    act(() => publish?.("dark"));
    expect(result.current).toBe("dark");

    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });
});
