// @vitest-environment jsdom

import { describe, expect, test, vi } from "vite-plus/test";

import { connectMarimoThemeFrame } from "../src/theme-frame.ts";

describe("Marimo theme frames", () => {
  test("tracks the resolved theme on the native editor document", async () => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const body = frame.contentDocument?.body;
    if (!body) {
      throw new Error("The iframe document must have a body");
    }
    body.dataset.theme = "light";
    const listener = vi.fn();

    const disconnect = connectMarimoThemeFrame(frame, listener);
    expect(listener).toHaveBeenLastCalledWith("light");

    body.dataset.theme = "dark";
    await vi.waitFor(() => expect(listener).toHaveBeenLastCalledWith("dark"));

    disconnect();
    body.dataset.theme = "light";
    await Promise.resolve();
    expect(listener).toHaveBeenLastCalledWith("dark");
  });
});
