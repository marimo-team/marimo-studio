import { SourceEvents } from "./source-events.ts";
import { SourcePanel } from "./source-panel.ts";
import {
  createSourceRemote,
  type SourceName,
  type SourceRemote,
} from "./source-remote.ts";
import {
  type SourceObserver,
  type SourceState,
  SyncedSource,
} from "./source-sync.ts";

const SOURCE_NAMES: readonly SourceName[] = ["index.html", "app.css"];

export class SourceController {
  private readonly documents = new Map<SourceName, SyncedSource>();
  private readonly states = new Map<SourceName, SourceState>();
  private readonly events = new SourceEvents();
  private readonly remote: SourceRemote;
  private panel!: SourcePanel;
  private view: string;
  private active: SourceName;
  private transition = 0;

  private constructor(
    private readonly supportPrefix: string,
    serverToken: string,
    initialView: string,
    private readonly storagePrefix: string,
    private readonly revealSource: () => void,
  ) {
    this.view = initialView;
    this.active = this.readActiveTab(initialView);
    this.remote = createSourceRemote(this.supportPrefix, serverToken);
  }

  static async create(
    supportPrefix: string,
    serverToken: string,
    initialView: string,
    storagePrefix: string,
    revealSource: () => void,
  ): Promise<SourceController> {
    const controller = new SourceController(
      supportPrefix,
      serverToken,
      initialView,
      storagePrefix,
      revealSource,
    );
    await controller.mount();
    return controller;
  }

  async switchView(view: string): Promise<boolean> {
    const transition = ++this.transition;
    if (!(await this.prepareViewChange()) || transition !== this.transition) {
      return false;
    }
    return await this.loadView(view, transition);
  }

  async prepareViewChange(): Promise<boolean> {
    if (await this.flush()) {
      return true;
    }
    this.revealBlockedSource();
    return false;
  }

  cancelSwitch(): void {
    this.transition += 1;
    this.documents.forEach((source) => source.cancelLoad());
  }

  async flush(): Promise<boolean> {
    const results = await Promise.all(
      SOURCE_NAMES.map((name) => this.documents.get(name)?.save() ?? true),
    );
    return results.every(Boolean);
  }

  get hasPendingChanges(): boolean {
    return SOURCE_NAMES.some(
      (name) => this.documents.get(name)?.hasPendingChanges,
    );
  }

  focusHtml(): void {
    this.activate("index.html");
    this.revealSource();
    this.panel.focusHtml();
  }

  requestMeasure(): void {
    this.panel.requestMeasure();
  }

  dispose(): void {
    this.events.close();
    this.documents.forEach((document) => document.dispose());
    this.panel.dispose();
  }

  private async mount(): Promise<void> {
    const observer: SourceObserver = {
      document: (name, content) => this.panel?.document(name, content),
      state: (state) => this.updateState(state),
    };
    for (const name of SOURCE_NAMES) {
      this.documents.set(name, new SyncedSource(name, this.remote, observer));
    }
    this.panel = await SourcePanel.create(this.view, this.active, {
      edit: (name, content) => this.documents.get(name)?.edit(content),
      save: (name) => void this.documents.get(name)?.save(),
      activate: (name) => this.activate(name),
      useDisk: () => this.documents.get(this.active)?.useDisk(),
      keepLocal: () => void this.documents.get(this.active)?.keepLocal(),
    });
    const loaded = await Promise.all(
      SOURCE_NAMES.map((name) => this.documents.get(name)!.load(this.view)),
    );
    this.openEvents();
    if (!loaded.every(Boolean)) {
      this.revealBlockedSource();
    }
  }

  private activate(name: SourceName): void {
    this.active = name;
    globalThis.localStorage.setItem(this.tabKey(), name);
    this.panel.activate(name);
    const state = this.states.get(name);
    if (state) {
      this.panel.state(state);
    }
  }

  private updateState(state: SourceState): void {
    this.states.set(state.name, state);
    this.panel?.state(state);
    if (state.phase === "conflict") {
      this.activate(state.name);
      this.revealSource();
    }
  }

  private revealBlockedSource(): void {
    const blocked = SOURCE_NAMES.find(
      (name) =>
        this.documents.get(name)?.hasConflict ||
        this.documents.get(name)?.hasPendingChanges ||
        this.states.get(name)?.phase === "error",
    );
    if (blocked) {
      this.activate(blocked);
      this.revealSource();
    }
  }

  private async loadView(view: string, transition: number): Promise<boolean> {
    this.documents.forEach((source) => source.beginLoad());
    const loaded = await Promise.allSettled(
      SOURCE_NAMES.map(async (name) => ({
        name,
        source: await this.documents.get(name)!.read(view),
      })),
    );
    if (transition !== this.transition) {
      return false;
    }
    if (this.hasPendingChanges) {
      this.documents.forEach((source) => source.cancelLoad());
      this.revealBlockedSource();
      return false;
    }
    let failed = false;
    for (const [index, result] of loaded.entries()) {
      if (result.status === "fulfilled") {
        this.documents.get(SOURCE_NAMES[index])?.cancelLoad();
      } else {
        failed = true;
        this.documents.get(SOURCE_NAMES[index])?.loadError(result.reason);
      }
    }
    if (failed) {
      this.revealBlockedSource();
      return false;
    }
    this.view = view;
    this.active = this.readActiveTab(view);
    for (const result of loaded) {
      if (result.status === "fulfilled") {
        const { name, source } = result.value;
        this.documents.get(name)?.open(view, source);
      }
    }
    this.panel.setView(view, this.active);
    const state = this.states.get(this.active);
    if (state) {
      this.panel.state(state);
    }
    this.openEvents();
    return true;
  }

  private openEvents(): void {
    this.events.open(
      `${this.supportPrefix}/${encodeURIComponent(this.view)}/dev/events`,
      () => this.documents.forEach((source) => void source.reconcile()),
      ({ path, revision }) => {
        void this.documents.get(path)?.externalChange(revision);
      },
    );
  }

  private tabKey(view = this.view): string {
    return `${this.storagePrefix}:source:${view}`;
  }

  private readActiveTab(view: string): SourceName {
    return globalThis.localStorage.getItem(this.tabKey(view)) === "app.css"
      ? "app.css"
      : "index.html";
  }
}
