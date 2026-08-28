import type { ViewNavigationIntent } from "@marimo-studio/protocol/preview-messages";
import type { Starter } from "@marimo-studio/protocol/provider-catalog";
import type { ViewList } from "@marimo-studio/protocol/views";

import type { StarterCatalogState } from "./catalog.ts";
import type { ViewRemote } from "./remote.ts";
import type { ViewLanding, ViewSelectionOwner } from "./transition.ts";

import { errorMessage } from "../../shared/errors.ts";

export interface ViewMessage {
  text: string;
  state: "warning" | "error";
}

export interface ViewSnapshot {
  current: string;
  defaultView: string;
  views: readonly string[];
  selecting?: string;
  starters: readonly Starter[];
  defaultStarter: string;
  starterCatalog: StarterCatalogState;
  creating: boolean;
  deleting: boolean;
  removing?: string;
  selectionMessage?: ViewMessage;
  createMessage?: ViewMessage;
  removeError?: string;
}

type Listener = () => void;

interface InventoryRequest {
  readonly generation: number;
  readonly promise: Promise<ViewList | undefined>;
}

export class ViewController {
  private readonly listeners = new Set<Listener>();
  private snapshot: ViewSnapshot;
  private refreshGeneration = 0;
  private mutationGeneration = 0;
  private inventoryRequest: InventoryRequest | undefined;
  private disposed = false;

  constructor(
    initialView: string,
    initialViews: string[],
    private readonly remote: ViewRemote,
    private readonly selectView: (
      view: string,
      landing: ViewLanding,
      navigation?: ViewNavigationIntent,
      signal?: AbortSignal,
      owner?: ViewSelectionOwner,
    ) => Promise<boolean>,
    private readonly prepareCurrentView: () => Promise<boolean>,
    private readonly cancelSelection: () => void,
    initialStarters: readonly Starter[] = [],
    initialDefaultStarter = "",
    private readonly settleView: (view: string) => Promise<boolean> = async () => true,
    private readonly releaseView: (view: string) => void = () => {},
    initialDefaultView = initialView,
  ) {
    this.snapshot = {
      current: initialView,
      defaultView: initialDefaultView,
      views: initialViews,
      starters: initialStarters,
      defaultStarter: initialDefaultStarter,
      starterCatalog: initialStarters.length > 0 ? { phase: "ready" } : { phase: "idle" },
      creating: false,
      deleting: false,
    };
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): ViewSnapshot => this.snapshot;

  async choose(
    view: string,
    landing: ViewLanding = "preserve",
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
    owner: ViewSelectionOwner = "browser",
  ): Promise<boolean> {
    signal?.throwIfAborted();
    if (
      this.disposed ||
      this.snapshot.creating ||
      this.snapshot.deleting ||
      !this.snapshot.views.includes(view)
    ) {
      return false;
    }
    const generation = ++this.mutationGeneration;
    this.update({ selecting: view, selectionMessage: undefined });
    try {
      const selected = await this.selectWithinMutation(
        view,
        landing,
        navigation,
        generation,
        signal,
        owner,
      );
      if (!selected && !signal?.aborted && this.isCurrentMutation(generation)) {
        this.update({
          selectionMessage: {
            text: `Could not open ${view}. The previous page remains active. Check Source and runtime status, then retry.`,
            state: "error",
          },
        });
      }
      return selected;
    } catch (cause) {
      if (!signal?.aborted && this.isCurrentMutation(generation)) {
        this.update({
          selectionMessage: {
            text: `${errorMessage(cause)} The previous page remains active.`,
            state: "error",
          },
        });
      }
      return false;
    } finally {
      if (this.isCurrentMutation(generation)) {
        this.update({ selecting: undefined });
      }
    }
  }

  cancelPendingSelection(): void {
    if (this.disposed || this.snapshot.creating || this.snapshot.deleting) {
      return;
    }
    this.mutationGeneration += 1;
    this.cancelSelection();
    this.update({ selecting: undefined, selectionMessage: undefined });
  }

  private async selectWithinMutation(
    view: string,
    landing: ViewLanding,
    navigation: ViewNavigationIntent | undefined,
    generation: number,
    signal?: AbortSignal,
    owner: ViewSelectionOwner = "browser",
  ): Promise<boolean> {
    let selected: boolean;
    if (owner === "agent") {
      selected = await this.selectView(view, landing, navigation, signal, owner);
    } else if (signal) {
      selected = await this.selectView(view, landing, navigation, signal);
    } else if (navigation) {
      selected = await this.selectView(view, landing, navigation);
    } else {
      selected = await this.selectView(view, landing);
    }
    if (!selected || signal?.aborted || !this.isCurrentMutation(generation)) {
      return false;
    }
    this.update({ current: view, createMessage: undefined });
    return true;
  }

  async create(name: string, starter: string): Promise<boolean> {
    if (this.disposed || this.snapshot.creating || this.snapshot.deleting) {
      return false;
    }
    if (!/^[a-z][a-z0-9-]*$/.test(name)) {
      this.update({
        createMessage: {
          text: "Start with a lowercase letter. Use letters, numbers, and hyphens.",
          state: "error",
        },
      });
      return false;
    }
    const selected = this.snapshot.starters.find((candidate) => candidate.id === starter);
    if (!selected || !selected.availability.available) {
      this.update({
        createMessage: {
          text: selected?.availability.action ?? "Choose an available starting option.",
          state: "error",
        },
      });
      return false;
    }
    const generation = this.beginMutation({ creating: true, createMessage: undefined });
    try {
      const prepared = await this.prepareCurrentView();
      if (!this.isCurrentMutation(generation)) {
        return false;
      }
      if (!prepared) {
        this.update({
          createMessage: {
            text: "Resolve the current source before creating a page.",
            state: "error",
          },
        });
        return false;
      }
      const created = await this.remote.create(name, starter);
      if (!this.isCurrentMutation(generation)) {
        return false;
      }
      if (!this.snapshot.views.includes(created.name)) {
        this.update({ views: [...this.snapshot.views, created.name].sort() });
      }
      if (await this.selectWithinMutation(created.name, "authoring", undefined, generation)) {
        return true;
      }
      this.update({
        createMessage: {
          text: "Page created. Resolve the current source, then select it from Pages.",
          state: "warning",
        },
      });
      return false;
    } catch (cause) {
      if (this.isCurrentMutation(generation)) {
        this.update({ createMessage: { text: errorMessage(cause), state: "error" } });
      }
      return false;
    } finally {
      this.finishMutation(generation, { creating: false });
    }
  }

  beginRemoval(view: string): void {
    if (
      this.disposed ||
      this.snapshot.creating ||
      this.snapshot.deleting ||
      this.snapshot.views.length < 2
    ) {
      return;
    }
    this.update({ removing: view, removeError: undefined });
  }

  cancelRemoval(): void {
    this.update({ removing: undefined, removeError: undefined });
  }

  async deleteSelected(): Promise<boolean> {
    const name = this.snapshot.removing;
    if (
      this.disposed ||
      !name ||
      this.snapshot.creating ||
      this.snapshot.deleting ||
      !this.snapshot.views.includes(name)
    ) {
      return false;
    }
    const generation = this.beginMutation({ deleting: true, removeError: undefined });
    try {
      const prepared = name !== this.snapshot.current || (await this.prepareCurrentView());
      if (!this.isCurrentMutation(generation)) {
        return false;
      }
      if (!prepared) {
        this.update({ removeError: "Resolve the current source before removing this page." });
        return false;
      }
      if (name === this.snapshot.current) {
        const inventory = await this.loadInventory();
        if (!this.isCurrentMutation(generation)) {
          return false;
        }
        if (!inventory) {
          this.update({
            removeError:
              this.snapshot.starterCatalog.phase === "error"
                ? this.snapshot.starterCatalog.message
                : "Could not load available pages.",
          });
          return false;
        }
        const names = inventory.views.map((view) => view.name);
        const successor =
          inventory.default_view !== name && names.includes(inventory.default_view)
            ? inventory.default_view
            : names.find((view) => view !== name);
        if (
          !successor ||
          !(await this.selectWithinMutation(successor, "develop", undefined, generation))
        ) {
          if (this.isCurrentMutation(generation)) {
            this.update({ removeError: "Select another page before removing this one." });
          }
          return false;
        }
        const settled = await this.settleView(successor);
        if (!this.isCurrentMutation(generation)) {
          return false;
        }
        if (!settled) {
          if (this.isCurrentMutation(generation)) {
            this.update({ removeError: "Wait for the selected page to finish loading." });
          }
          return false;
        }
      }
      this.releaseView(name);
      const removed = await this.remote.remove(name);
      if (!this.isCurrentMutation(generation)) {
        return false;
      }
      const remaining = removed.views.map((view) => view.name);
      this.acceptInventory(removed);
      if (!remaining.includes(this.snapshot.current)) {
        if (
          !(await this.selectWithinMutation(removed.default_view, "develop", undefined, generation))
        ) {
          this.update({ removeError: "Select an available page to continue." });
          return false;
        }
      }
      this.update({ removing: undefined });
      return true;
    } catch (cause) {
      if (this.isCurrentMutation(generation)) {
        this.update({ removeError: errorMessage(cause) });
      }
      return false;
    } finally {
      this.finishMutation(generation, { deleting: false });
    }
  }

  dismiss(): void {
    this.update({
      removing: undefined,
      removeError: undefined,
      selectionMessage: undefined,
      createMessage: undefined,
    });
  }

  dismissPanels(): void {
    this.update({ removing: undefined, removeError: undefined, createMessage: undefined });
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.refreshGeneration += 1;
    this.mutationGeneration += 1;
    this.cancelSelection();
    this.listeners.clear();
  }

  async ensureStarterCatalog(): Promise<void> {
    if (this.snapshot.starterCatalog.phase !== "ready") {
      await this.refreshInventory();
    }
  }

  async refreshInventory(): Promise<void> {
    if (this.disposed) {
      return;
    }
    if (this.snapshot.creating || this.snapshot.deleting) {
      return;
    }
    await this.loadInventory();
  }

  async ensureAvailable(view: string, signal?: AbortSignal): Promise<boolean> {
    signal?.throwIfAborted();
    if (this.snapshot.views.includes(view)) {
      return true;
    }
    const inventory = await abortable(this.loadInventory(), signal);
    signal?.throwIfAborted();
    const views = inventory?.views.map((item) => item.name) ?? [];
    if (!inventory) {
      return false;
    }
    return views.includes(view);
  }

  private update(next: Partial<ViewSnapshot>): void {
    if (this.disposed) {
      return;
    }
    this.snapshot = { ...this.snapshot, ...next };
    this.listeners.forEach((listener) => listener());
  }

  private beginMutation(next: Partial<ViewSnapshot>): number {
    this.cancelSelection();
    const generation = ++this.mutationGeneration;
    this.refreshGeneration += 1;
    this.update({ selecting: undefined, ...next });
    return generation;
  }

  private finishMutation(generation: number, next: Partial<ViewSnapshot>): void {
    if (!this.isCurrentMutation(generation)) {
      return;
    }
    this.update(next);
    void this.refreshInventory().catch((cause: unknown) => {
      if (!this.disposed) {
        console.warn("Studio views could not be refreshed", cause);
      }
    });
  }

  private isCurrentMutation(generation: number): boolean {
    return !this.disposed && generation === this.mutationGeneration;
  }

  private loadInventory(): Promise<ViewList | undefined> {
    if (this.inventoryRequest?.generation === this.refreshGeneration) {
      return this.inventoryRequest.promise;
    }
    const generation = ++this.refreshGeneration;
    this.update({ starterCatalog: { phase: "loading" } });
    const request = { generation, promise: this.fetchInventory(generation) };
    this.inventoryRequest = request;
    void request.promise.finally(() => {
      if (this.inventoryRequest === request) {
        this.inventoryRequest = undefined;
      }
    });
    return request.promise;
  }

  private async fetchInventory(generation: number): Promise<ViewList | undefined> {
    try {
      const inventory = await this.remote.list();
      if (this.disposed || generation !== this.refreshGeneration) {
        return undefined;
      }
      const previousCurrent = this.snapshot.current;
      const nextViews = new Set(inventory.views.map((view) => view.name));
      const removedViews = this.snapshot.views.filter((view) => !nextViews.has(view));
      this.acceptInventory(inventory);
      for (const view of removedViews) {
        if (view !== previousCurrent) {
          this.releaseView(view);
        }
      }
      await this.applyInventorySelection(inventory);
      if (this.disposed || generation !== this.refreshGeneration) {
        return undefined;
      }
      if (removedViews.includes(previousCurrent) && this.snapshot.current !== previousCurrent) {
        this.releaseView(previousCurrent);
      }
      return inventory;
    } catch (cause) {
      if (!this.disposed && generation === this.refreshGeneration) {
        this.update({
          starterCatalog: { phase: "error", message: errorMessage(cause) },
        });
      }
      return undefined;
    }
  }

  private acceptInventory(inventory: ViewList): void {
    const views = inventory.views.map((view) => view.name);
    this.update({
      views,
      defaultView: inventory.default_view,
      starters: inventory.starters,
      defaultStarter: inventory.default_starter,
      starterCatalog: { phase: "ready" },
    });
  }

  private async applyInventorySelection(inventory: ViewList): Promise<void> {
    const views = inventory.views.map((view) => view.name);
    if (!views.includes(this.snapshot.current)) {
      await this.choose(inventory.default_view);
    }
  }
}

const abortable = async <T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> => {
  if (!signal) {
    return operation;
  }
  signal.throwIfAborted();
  let abort = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    abort = () => reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
  });
  try {
    return await Promise.race([operation, aborted]);
  } finally {
    signal.removeEventListener("abort", abort);
  }
};
