import type { Starter } from "@marimo-studio/protocol/provider-catalog";
import type { ViewList } from "@marimo-studio/protocol/views";

import type { ViewRemote } from "./remote.ts";

import { errorMessage } from "../../shared/errors.ts";

export type StarterCatalogState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "ready" }
  | { phase: "error"; message: string };

export interface StarterCatalogSnapshot {
  state: StarterCatalogState;
  generation: string;
  starters: readonly Starter[];
  defaultStarter: string;
}

type Listener = () => void;

export class StarterCatalogController {
  private readonly listeners = new Set<Listener>();
  private snapshot: StarterCatalogSnapshot;
  private generation = 0;
  private inFlight: { generation: number; request: Promise<ViewList | undefined> } | undefined;
  private disposed = false;

  constructor(
    private readonly list: ViewRemote["list"],
    initialStarters: readonly Starter[] = [],
    initialDefaultStarter = "",
    initialGeneration = "",
  ) {
    this.snapshot = {
      state: initialStarters.length > 0 ? { phase: "ready" } : { phase: "idle" },
      generation: initialGeneration,
      starters: initialStarters,
      defaultStarter: initialDefaultStarter,
    };
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): StarterCatalogSnapshot => this.snapshot;

  async ensure(): Promise<void> {
    if (this.snapshot.state.phase === "ready") {
      return;
    }
    await this.refresh();
  }

  refresh(): Promise<ViewList | undefined> {
    if (this.disposed) {
      return Promise.resolve(undefined);
    }
    if (this.snapshot.state.phase === "loading" && this.inFlight?.generation === this.generation) {
      return this.inFlight.request;
    }
    const generation = ++this.generation;
    const request = Promise.resolve().then(() => this.load(generation));
    this.inFlight = { generation, request };
    this.publish({ ...this.snapshot, state: { phase: "loading" } });
    void request.finally(() => {
      if (this.inFlight?.generation === generation) {
        this.inFlight = undefined;
      }
    });
    return request;
  }

  accept(inventory: Pick<ViewList, "default_starter" | "generation" | "starters">): void {
    if (this.disposed) {
      return;
    }
    this.generation += 1;
    this.publish({
      state: { phase: "ready" },
      generation: inventory.generation,
      starters: inventory.starters,
      defaultStarter: inventory.default_starter,
    });
  }

  invalidate(): void {
    this.generation += 1;
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.generation += 1;
    this.listeners.clear();
  }

  private async load(generation: number): Promise<ViewList | undefined> {
    try {
      const inventory = await this.list();
      if (this.disposed || generation !== this.generation) {
        return undefined;
      }
      this.publish({
        state: { phase: "ready" },
        generation: inventory.generation,
        starters: inventory.starters,
        defaultStarter: inventory.default_starter,
      });
      return inventory;
    } catch (cause) {
      if (!this.disposed && generation === this.generation) {
        this.publish({
          ...this.snapshot,
          state: { phase: "error", message: errorMessage(cause) },
        });
      }
      return undefined;
    }
  }

  private publish(snapshot: StarterCatalogSnapshot): void {
    if (this.disposed) {
      return;
    }
    this.snapshot = snapshot;
    this.listeners.forEach((listener) => listener());
  }
}
