import type { ViewNavigationIntent } from "@marimo-studio/protocol/preview-messages";

import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import {
  nextPreviewDocumentLifecycleId,
  type PreviewController,
  type PreviewFrameState,
} from "./controller.ts";
import { RuntimeDiagnostics } from "./runtime-diagnostics.ts";
import { previewStatus } from "./status.ts";

const PREVIEW_VIEW_CACHE_SIZE = 3;
const WASM_PREVIEW_VIEW_CACHE_SIZE = 1;

export interface CachedPreview {
  readonly id: string;
  readonly runtime: string;
  controller?: PreviewController;
  frame?: HTMLIFrameElement;
  lastUsed: number;
  navigation?: ViewNavigationIntent;
  stale: boolean;
  state?: PreviewFrameState;
  view?: string;
}

const startingFrameState = (
  runtime: string,
  view: string,
  url: string,
  lifecycleId: number,
): PreviewFrameState => {
  const runtimeStatus = new RuntimeDiagnostics({ runtime, view }).report();
  return {
    url,
    lifecycleId,
    runtimeStatus,
    status: previewStatus(runtime, runtimeStatus.current),
  };
};

const sameNavigation = (left: ViewNavigationIntent, right: ViewNavigationIntent): boolean =>
  left.query === right.query && left.hash === right.hash;

export class PreviewFrames {
  readonly slots: CachedPreview[] = [];
  readonly ids: readonly string[];
  private lastUsed = 0;

  constructor(
    runtimes: readonly string[],
    private readonly viewUrl: (
      view: string,
      runtime: string,
      navigation: ViewNavigationIntent,
    ) => string,
    private readonly released: (view: string) => void,
  ) {
    for (const runtime of runtimes) {
      const cacheSize =
        runtime === DEFAULT_RUNTIME_ID ? PREVIEW_VIEW_CACHE_SIZE : WASM_PREVIEW_VIEW_CACHE_SIZE;
      for (let index = 0; index < cacheSize; index += 1) {
        this.slots.push({
          id: index === 0 ? runtime : `${runtime}:${index}`,
          runtime,
          lastUsed: 0,
          stale: false,
        });
      }
    }
    this.ids = this.slots.map(({ id }) => id);
  }

  attach(frames: ReadonlyMap<string, HTMLIFrameElement>): void {
    for (const slot of this.slots) {
      slot.frame = frames.get(slot.id);
    }
  }

  dispose(): void {
    this.slots.forEach((slot) => this.release(slot));
  }

  select(runtime: string, view: string, navigation: ViewNavigationIntent): CachedPreview {
    const existing = this.find(runtime, view);
    if (existing) {
      this.touch(existing);
      if (!sameNavigation(existing.navigation!, navigation)) {
        existing.navigation = navigation;
        if (!existing.controller && existing.state) {
          existing.state = {
            ...existing.state,
            url: this.viewUrl(view, runtime, navigation),
          };
        }
      }
      return existing;
    }
    const candidates = this.slots.filter((slot) => slot.runtime === runtime);
    const selected =
      candidates.find(({ view: assigned }) => assigned === undefined) ??
      candidates.reduce((oldest, slot) => (slot.lastUsed < oldest.lastUsed ? slot : oldest));
    this.release(selected);
    selected.view = view;
    selected.navigation = navigation;
    selected.state = startingFrameState(
      runtime,
      view,
      this.viewUrl(view, runtime, navigation),
      nextPreviewDocumentLifecycleId(),
    );
    this.touch(selected);
    return selected;
  }

  find(runtime: string, view: string): CachedPreview | undefined {
    return this.slots.find((slot) => slot.runtime === runtime && slot.view === view);
  }

  private touch(slot: CachedPreview): void {
    this.lastUsed += 1;
    slot.lastUsed = this.lastUsed;
  }

  release(slot: CachedPreview): void {
    const releasedView = slot.view;
    slot.controller?.deactivate();
    slot.controller?.dispose();
    slot.controller = undefined;
    slot.stale = false;
    slot.state = undefined;
    slot.navigation = undefined;
    slot.view = undefined;
    slot.lastUsed = 0;
    if (slot.frame) {
      delete slot.frame.dataset.sessionId;
      slot.frame.src = "about:blank";
    }
    if (releasedView !== undefined) {
      this.released(releasedView);
    }
  }
}
