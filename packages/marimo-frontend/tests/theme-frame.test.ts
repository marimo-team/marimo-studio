import { afterEach, describe, expect, test, vi } from "vite-plus/test";

import { connectMarimoThemeFrame } from "../src/theme-frame.ts";

afterEach(() => vi.unstubAllGlobals());

class FrameMutationObserver {
  static latest: FrameMutationObserver | undefined;

  private target: HTMLElement | undefined;

  constructor(private readonly callback: MutationCallback) {
    FrameMutationObserver.latest = this;
  }

  observe(target: Node): void {
    this.target = target as HTMLElement;
  }

  disconnect(): void {
    this.target = undefined;
  }

  publish(): void {
    if (this.target) {
      this.callback([], this as unknown as MutationObserver);
    }
  }

  takeRecords(): MutationRecord[] {
    return [];
  }
}

describe("Marimo theme frames", () => {
  test("tracks the resolved theme on the native editor document", () => {
    const body = { dataset: { theme: "light" } } as unknown as HTMLElement;
    const frameEvents = new EventTarget();
    const frame = {
      contentWindow: {
        document: { body },
      },
      addEventListener: frameEvents.addEventListener.bind(frameEvents),
      removeEventListener: frameEvents.removeEventListener.bind(frameEvents),
    } as unknown as HTMLIFrameElement;
    const listener = vi.fn();
    vi.stubGlobal("MutationObserver", FrameMutationObserver);

    const disconnect = connectMarimoThemeFrame(frame, listener);
    expect(listener).toHaveBeenLastCalledWith("light");

    body.dataset.theme = "dark";
    FrameMutationObserver.latest?.publish();
    expect(listener).toHaveBeenLastCalledWith("dark");

    disconnect();
    body.dataset.theme = "light";
    FrameMutationObserver.latest?.publish();
    expect(listener).toHaveBeenLastCalledWith("dark");
  });
});
