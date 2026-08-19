import type { ViewRemote } from "./remote.ts";
import type { ViewLanding } from "./transition.ts";

import { errorMessage } from "../../shared/errors.ts";

export interface ViewMessage {
  text: string;
  state: "warning" | "error";
}

export interface ViewSnapshot {
  current: string;
  views: readonly string[];
  creating: boolean;
  deleting: boolean;
  removing?: string;
  createMessage?: ViewMessage;
  removeError?: string;
}

type Listener = () => void;

export class ViewController {
  private readonly listeners = new Set<Listener>();
  private snapshot: ViewSnapshot;
  private refreshGeneration = 0;
  private disposed = false;

  constructor(
    initialView: string,
    initialViews: string[],
    private readonly remote: ViewRemote,
    private readonly selectView: (view: string, landing: ViewLanding) => Promise<boolean>,
    private readonly prepareCurrentView: () => Promise<boolean>,
  ) {
    this.snapshot = {
      current: initialView,
      views: initialViews,
      creating: false,
      deleting: false,
    };
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): ViewSnapshot => this.snapshot;

  async choose(view: string, landing: ViewLanding = "split"): Promise<boolean> {
    if (this.disposed || !this.snapshot.views.includes(view)) {
      return false;
    }
    if (!(await this.selectView(view, landing)) || this.disposed) {
      return false;
    }
    this.update({ current: view, createMessage: undefined });
    return true;
  }

  async create(name: string): Promise<boolean> {
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
    this.beginMutation({ creating: true, createMessage: undefined });
    try {
      const prepared = await this.prepareCurrentView();
      if (this.disposed) {
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
      const created = await this.remote.create(name);
      if (this.disposed) {
        return false;
      }
      if (!this.snapshot.views.includes(created.name)) {
        this.update({ views: [...this.snapshot.views, created.name].sort() });
      }
      if (await this.choose(created.name, "authoring")) {
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
      if (!this.disposed) {
        this.update({ createMessage: { text: errorMessage(cause), state: "error" } });
      }
      return false;
    } finally {
      this.finishMutation({ creating: false });
    }
  }

  beginRemoval(view: string): void {
    if (this.disposed || this.snapshot.deleting || this.snapshot.views.length < 2) {
      return;
    }
    this.update({ removing: view, removeError: undefined });
  }

  cancelRemoval(): void {
    this.update({ removing: undefined, removeError: undefined });
  }

  async deleteSelected(): Promise<boolean> {
    const name = this.snapshot.removing;
    if (this.disposed || !name || this.snapshot.deleting || !this.snapshot.views.includes(name)) {
      return false;
    }
    this.beginMutation({ deleting: true, removeError: undefined });
    try {
      const prepared = name !== this.snapshot.current || (await this.prepareCurrentView());
      if (this.disposed) {
        return false;
      }
      if (!prepared) {
        this.update({ removeError: "Resolve the current source before removing this view." });
        return false;
      }
      if (name === this.snapshot.current) {
        const inventory = await this.remote.list();
        if (this.disposed) {
          return false;
        }
        const successor =
          inventory.default_view !== name && inventory.views.includes(inventory.default_view)
            ? inventory.default_view
            : inventory.views.find((view) => view !== name);
        if (!successor || !(await this.choose(successor))) {
          if (!this.disposed) {
            this.update({ removeError: "Select another view before removing this one." });
          }
          return false;
        }
      }
      const removed = await this.remote.remove(name);
      if (this.disposed) {
        return false;
      }
      this.update({ views: removed.views });
      if (!removed.views.includes(this.snapshot.current)) {
        if (!(await this.choose(removed.default_view))) {
          this.update({ removeError: "Select an available view to continue." });
          return false;
        }
      }
      this.update({ removing: undefined });
      return true;
    } catch (cause) {
      if (!this.disposed) {
        this.update({ removeError: errorMessage(cause) });
      }
      return false;
    } finally {
      this.finishMutation({ deleting: false });
    }
  }

  dismiss(): void {
    this.update({ removing: undefined, removeError: undefined, createMessage: undefined });
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.refreshGeneration += 1;
    this.listeners.clear();
  }

  async refreshInventory(): Promise<void> {
    if (this.disposed) {
      return;
    }
    if (this.snapshot.creating || this.snapshot.deleting) {
      return;
    }
    const generation = ++this.refreshGeneration;
    const payload = await this.remote.list();
    if (this.disposed || generation !== this.refreshGeneration) {
      return;
    }
    this.update({ views: payload.views });
    if (!payload.views.includes(this.snapshot.current)) {
      await this.choose(payload.default_view);
    }
  }

  async ensureAvailable(view: string): Promise<boolean> {
    if (this.snapshot.views.includes(view)) {
      return true;
    }
    const payload = await this.remote.list();
    if (this.disposed || !payload.views.includes(view)) {
      return false;
    }
    this.refreshGeneration += 1;
    this.update({ views: payload.views });
    return true;
  }

  private update(next: Partial<ViewSnapshot>): void {
    if (this.disposed) {
      return;
    }
    this.snapshot = { ...this.snapshot, ...next };
    this.listeners.forEach((listener) => listener());
  }

  private beginMutation(next: Partial<ViewSnapshot>): void {
    this.refreshGeneration += 1;
    this.update(next);
  }

  private finishMutation(next: Partial<ViewSnapshot>): void {
    if (this.disposed) {
      return;
    }
    this.update(next);
    void this.refreshInventory().catch((cause: unknown) => {
      if (!this.disposed) {
        console.warn("Studio views could not be refreshed", cause);
      }
    });
  }
}
