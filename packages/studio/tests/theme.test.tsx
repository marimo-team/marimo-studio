import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi } from "vite-plus/test";

import type { StudioTheme, ThemeFrameConnector } from "../src/shared/theme.tsx";

import { useResolvedStudioTheme } from "../src/shared/theme.tsx";

describe("Studio theme", () => {
  test("subscribes to the system color scheme as an external store", () => {
    let dark = false;
    let publish: (() => void) | undefined;
    const remove = vi.fn();
    vi.stubGlobal("matchMedia", () => ({
      get matches() {
        return dark;
      },
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (_name: string, listener: () => void) => {
        publish = listener;
      },
      removeEventListener: remove,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    }));
    const { result, unmount } = renderHook(() => useResolvedStudioTheme(null));

    expect(result.current).toBe("light");
    act(() => {
      dark = true;
      publish?.();
    });
    expect(result.current).toBe("dark");

    unmount();
    expect(remove).toHaveBeenCalledOnce();
  });

  test("follows the native editor theme and disconnects with the shell", () => {
    let publish: ((theme: StudioTheme | undefined) => void) | undefined;
    const disconnect = vi.fn();
    const connect: ThemeFrameConnector = (_frame, listener) => {
      publish = listener;
      return disconnect;
    };
    const frame = document.createElement("iframe");
    const { result, rerender, unmount } = renderHook(
      ({ currentFrame }: { currentFrame: HTMLIFrameElement }) =>
        useResolvedStudioTheme(currentFrame, connect),
      { initialProps: { currentFrame: frame } },
    );

    expect(result.current).toBe("light");
    act(() => publish?.("dark"));
    expect(result.current).toBe("dark");

    rerender({ currentFrame: document.createElement("iframe") });
    expect(result.current).toBe("light");

    unmount();
    expect(disconnect).toHaveBeenCalledTimes(2);
  });
});
