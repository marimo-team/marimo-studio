import { ViewMenu } from "./view-menu.ts";
import type { ViewRemote } from "./view-remote.ts";

export class ViewController {
  private current: string;
  private views: string[];
  private readonly events: EventSource;
  private readonly menu: ViewMenu;
  private refreshGeneration = 0;
  private creating = false;
  private deleting = false;
  private removing: string | undefined;

  constructor(
    initialView: string,
    initialViews: string[],
    private readonly remote: ViewRemote,
    eventsUrl: string,
    private readonly selectView: (
      view: string,
      created: boolean,
    ) => Promise<boolean>,
    private readonly prepareCurrentView: () => Promise<boolean>,
    private readonly recoverView: (view: string) => void,
  ) {
    this.current = initialView;
    this.views = initialViews;
    this.menu = new ViewMenu({
      choose: (view) => void this.choose(view),
      create: (name) => void this.create(name),
      beginRemoval: (view) => this.confirmRemoval(view),
      cancelRemoval: () => this.cancelRemoval(),
      confirmRemoval: () => void this.deleteSelected(),
      dismiss: () => this.dismiss(),
    });
    this.render();
    this.events = new EventSource(eventsUrl);
    const refresh = () => void this.refresh().catch(() => undefined);
    this.events.addEventListener("ready", refresh);
    this.events.addEventListener("change", refresh);
  }

  async choose(view: string, created = false): Promise<boolean> {
    if (!this.views.includes(view)) {
      return false;
    }
    if (!(await this.selectView(view, created))) {
      return false;
    }
    this.current = view;
    this.render();
    this.menu.close();
    return true;
  }

  dispose(): void {
    this.events.close();
  }

  private async create(name: string): Promise<void> {
    if (this.creating || this.deleting) {
      return;
    }
    if (!/^[a-z][a-z0-9-]*$/.test(name)) {
      this.menu.showCreateMessage(
        "Start with a lowercase letter. Use letters, numbers, and hyphens.",
        "error",
      );
      return;
    }
    this.menu.clearCreateMessage();
    this.setCreating(true);
    try {
      if (!(await this.prepareCurrentView())) {
        this.menu.showCreateMessage(
          "Resolve the current source before creating a view.",
          "error",
        );
        return;
      }
      const created = await this.remote.create(name);
      if (!this.views.includes(created.name)) {
        this.views = [...this.views, created.name].sort();
        this.render();
      }
      if (await this.choose(created.name, true)) {
        this.menu.resetCreate();
      } else {
        this.menu.showCreateMessage(
          "View created. Resolve the current source, then select it from Views.",
          "warning",
        );
      }
    } catch (cause) {
      this.menu.showCreateMessage(errorMessage(cause), "error");
    } finally {
      this.setCreating(false);
    }
  }

  private async refresh(): Promise<void> {
    if (this.creating || this.deleting) {
      return;
    }
    const generation = ++this.refreshGeneration;
    const payload = await this.remote.list();
    if (generation !== this.refreshGeneration) {
      return;
    }
    this.views = payload.views;
    if (!this.views.includes(this.current)) {
      await this.choose(payload.default_view);
      return;
    }
    this.render();
  }

  private confirmRemoval(view: string): void {
    if (this.deleting || this.views.length < 2) {
      return;
    }
    this.removing = view;
    this.render();
    this.menu.showRemoval(view);
  }

  private cancelRemoval(): void {
    const view = this.removing;
    this.removing = undefined;
    this.render();
    this.menu.hideRemoval(view);
  }

  private async deleteSelected(): Promise<void> {
    const name = this.removing;
    if (!name || this.deleting || !this.views.includes(name)) {
      return;
    }
    this.menu.clearRemovalError();
    this.setDeleting(true);
    try {
      if (name === this.current && !(await this.prepareCurrentView())) {
        this.menu.showRemovalError(
          "Resolve the current source before removing this view.",
        );
        return;
      }
      const removed = await this.remote.remove(name);
      this.views = removed.views;
      if (name === this.current) {
        if (!(await this.choose(removed.default_view))) {
          this.recoverView(removed.default_view);
          return;
        }
      } else {
        this.render();
        this.menu.close();
      }
    } catch (cause) {
      this.menu.showRemovalError(errorMessage(cause));
    } finally {
      this.setDeleting(false);
    }
  }

  private dismiss(): void {
    this.removing = undefined;
    this.render();
  }

  private render(): void {
    this.menu.render(
      this.current,
      this.views,
      this.removing,
      this.deleting,
    );
  }

  private setCreating(creating: boolean): void {
    this.creating = creating;
    this.menu.setCreating(creating);
  }

  private setDeleting(deleting: boolean): void {
    this.deleting = deleting;
    this.menu.setDeleting(deleting);
  }
}

const errorMessage = (cause: unknown): string =>
  cause instanceof Error ? cause.message : String(cause);
