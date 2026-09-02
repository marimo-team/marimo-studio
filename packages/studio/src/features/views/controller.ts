import type { ViewNavigationIntent } from "@marimo-studio/protocol/preview-messages";
import type { Starter } from "@marimo-studio/protocol/provider-catalog";

import { type ViewList, viewNameError } from "@marimo-studio/protocol/views";

import type { StarterCatalogState } from "./catalog.ts";
import type { ViewRemote } from "./remote.ts";
import type { ViewLanding, ViewSelectionOwner } from "./transition.ts";

import { errorMessage } from "../../shared/errors.ts";

export interface ViewMessage {
  text: string;
  state: "warning" | "error";
}

export interface ViewSnapshot {
  catalogGeneration?: string;
  current: string;
  defaultView: string;
  views: readonly string[];
  viewGenerations: Readonly<Record<string, string>>;
  selecting?: string;
  starters: readonly Starter[];
  defaultStarter: string;
  starterCatalog: StarterCatalogState;
  creating: boolean;
  deleting: boolean;
  removing?: string;
  removingCatalogGeneration?: string;
  removingGeneration?: string;
  selectionMessage?: ViewMessage;
  createMessage?: ViewMessage;
  removeError?: string;
  removeMessage?: ViewMessage;
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
  private inventoryRefreshRequested = false;
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
    private readonly replaceView: (view: string) => void = () => {},
  ) {
    this.snapshot = {
      current: initialView,
      defaultView: initialDefaultView,
      views: initialViews,
      viewGenerations: {},
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
            text: `Could not open ${view}. The previous view remains active. Check Source and runtime status, then retry.`,
            state: "error",
          },
        });
      }
      return selected;
    } catch (cause) {
      if (!signal?.aborted && this.isCurrentMutation(generation)) {
        this.update({
          selectionMessage: {
            text: `${errorMessage(cause)} The previous view remains active.`,
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

  async create(name: string, starter: string, catalogGeneration: string): Promise<boolean> {
    if (this.disposed || this.snapshot.creating || this.snapshot.deleting || !catalogGeneration) {
      return false;
    }
    const nameError = viewNameError(name);
    if (nameError) {
      this.update({
        createMessage: {
          text: nameError,
          state: "error",
        },
      });
      return false;
    }
    if (this.snapshot.catalogGeneration !== catalogGeneration) {
      this.update({
        createMessage: {
          text: "The view catalog changed. Close this form, then create the view again.",
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
            text: "Resolve the current source before creating a view.",
            state: "error",
          },
        });
        return false;
      }
      const created = await this.remote.create(name, starter, catalogGeneration);
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
          text: "View created. Resolve the current source, then select it from Views.",
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

  beginRemoval(view: string, catalogGeneration: string, generation: string): void {
    if (
      this.disposed ||
      this.snapshot.creating ||
      this.snapshot.deleting ||
      this.snapshot.views.length < 2 ||
      this.snapshot.catalogGeneration !== catalogGeneration ||
      this.snapshot.viewGenerations[view] !== generation
    ) {
      return;
    }
    this.update({
      removing: view,
      removingCatalogGeneration: catalogGeneration,
      removingGeneration: generation,
      removeError: undefined,
      removeMessage: undefined,
    });
  }

  cancelRemoval(): void {
    this.update({
      removing: undefined,
      removingCatalogGeneration: undefined,
      removingGeneration: undefined,
      removeError: undefined,
    });
  }

  async deleteSelected(): Promise<boolean> {
    const name = this.snapshot.removing;
    const expectedCatalogGeneration = this.snapshot.removingCatalogGeneration;
    const expectedGeneration = this.snapshot.removingGeneration;
    if (
      this.disposed ||
      !name ||
      !expectedCatalogGeneration ||
      !expectedGeneration ||
      this.snapshot.creating ||
      this.snapshot.deleting ||
      !this.snapshot.views.includes(name)
    ) {
      return false;
    }
    const generation = this.beginMutation({ deleting: true, removeError: undefined });
    try {
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
                : "Could not load available views.",
          });
          return false;
        }
        const currentGeneration = inventory.views.find((view) => view.name === name)?.generation;
        if (
          inventory.generation !== expectedCatalogGeneration ||
          currentGeneration !== expectedGeneration
        ) {
          this.update({
            removeError: `View ${name} was replaced. Close this confirmation, then remove the current view.`,
          });
          return false;
        }
        const prepared = await this.prepareCurrentView();
        if (!this.isCurrentMutation(generation)) {
          return false;
        }
        if (!prepared) {
          this.update({ removeError: "Resolve the current source before removing this view." });
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
            this.update({ removeError: "Select another view before removing this one." });
          }
          return false;
        }
        const settled = await this.settleView(successor);
        if (!this.isCurrentMutation(generation)) {
          return false;
        }
        if (!settled) {
          if (this.isCurrentMutation(generation)) {
            this.update({ removeError: "Wait for the selected view to finish loading." });
          }
          return false;
        }
      }
      const removed = await this.remote.remove(name, expectedCatalogGeneration, expectedGeneration);
      if (!this.isCurrentMutation(generation)) {
        return false;
      }
      this.releaseView(name);
      const remaining = removed.views.map((view) => view.name);
      this.acceptInventory(removed);
      if (!remaining.includes(this.snapshot.current)) {
        if (
          !(await this.selectWithinMutation(removed.default_view, "develop", undefined, generation))
        ) {
          this.update({ removeError: "Select an available view to continue." });
          return false;
        }
      }
      this.update({
        removing: undefined,
        removingCatalogGeneration: undefined,
        removingGeneration: undefined,
        removeMessage: removed.cleanup
          ? {
              text: `View ${name} was removed. Files awaiting cleanup remain at ${removed.cleanup}.`,
              state: "warning",
            }
          : undefined,
      });
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
      removingCatalogGeneration: undefined,
      removingGeneration: undefined,
      removeError: undefined,
      removeMessage: undefined,
      selectionMessage: undefined,
      createMessage: undefined,
    });
  }

  dismissPanels(): void {
    this.update({
      removing: undefined,
      removingCatalogGeneration: undefined,
      removingGeneration: undefined,
      removeError: undefined,
      createMessage: undefined,
    });
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.refreshGeneration += 1;
    this.mutationGeneration += 1;
    this.inventoryRefreshRequested = false;
    this.cancelSelection();
    this.listeners.clear();
  }

  async ensureStarterCatalog(): Promise<void> {
    if (
      this.snapshot.catalogGeneration === undefined ||
      this.snapshot.starterCatalog.phase !== "ready"
    ) {
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
    const current = this.inventoryRequest;
    if (current?.generation === this.refreshGeneration) {
      this.inventoryRefreshRequested = true;
      await current.promise;
      if (
        this.disposed ||
        this.snapshot.creating ||
        this.snapshot.deleting ||
        !this.inventoryRefreshRequested
      ) {
        return;
      }
      this.inventoryRefreshRequested = false;
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
    this.inventoryRefreshRequested = false;
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
      const previousGenerations = this.snapshot.viewGenerations;
      const nextViews = new Set(inventory.views.map((view) => view.name));
      const removedViews = this.snapshot.views.filter((view) => !nextViews.has(view));
      const replacedViews = inventory.views
        .filter(
          (view) =>
            previousGenerations[view.name] !== undefined &&
            previousGenerations[view.name] !== view.generation,
        )
        .map((view) => view.name);
      this.acceptInventory(inventory);
      replacedViews.forEach((view) => this.replaceView(view));
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
    const viewGenerations = Object.fromEntries(
      inventory.views.map((view) => [view.name, view.generation]),
    );
    this.update({
      catalogGeneration: inventory.generation,
      views,
      viewGenerations,
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
