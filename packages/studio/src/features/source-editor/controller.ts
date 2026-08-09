import type { SourceName } from "@marimo-studio/protocol/source-events";

import { appendUrlPath } from "@marimo-studio/protocol/url";

import { SourceEvents } from "./events.ts";
import { SOURCE_NAMES, sourceRecord } from "./files.ts";
import { createSourceRemote, type SourceRemote } from "./remote.ts";
import { type SourceObserver, type SourceState, SyncedSource } from "./sync.ts";

export interface SourceDocumentSnapshot {
  content: string;
  state: SourceState;
}

export interface SourceSnapshot {
  view: string;
  active: SourceName;
  documents: Record<SourceName, SourceDocumentSnapshot>;
  focusRequest: number;
}

type Listener = () => void;

export class SourceController {
  private readonly sources = new Map<SourceName, SyncedSource>();
  private readonly contents = new Map<SourceName, string>();
  private readonly states = new Map<SourceName, SourceState>();
  private readonly events = new SourceEvents();
  private readonly remote: SourceRemote;
  private readonly listeners = new Set<Listener>();
  private view: string;
  private active: SourceName;
  private focusRequest = 0;
  private transition = 0;
  private started = false;
  private disposed = false;
  private snapshot!: SourceSnapshot;

  constructor(
    private readonly supportUrl: (view: string) => string,
    serverToken: string,
    initialView: string,
    private readonly storagePrefix: string,
    private readonly revealSource: () => void,
  ) {
    this.view = initialView;
    this.active = this.readActiveTab(initialView);
    this.remote = createSourceRemote(this.supportUrl, serverToken);
    const observer: SourceObserver = {
      document: (name, content) => {
        this.contents.set(name, content);
        this.publish();
      },
      state: (state) => this.updateState(state),
    };
    for (const name of SOURCE_NAMES) {
      this.contents.set(name, "");
      this.states.set(name, { name, phase: "loading" });
      this.sources.set(name, new SyncedSource(name, this.remote, observer));
    }
    this.updateSnapshot();
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): SourceSnapshot => this.snapshot;

  async start(): Promise<void> {
    if (this.started || this.disposed) {
      return;
    }
    this.started = true;
    const loaded = await Promise.all(
      SOURCE_NAMES.map(async (name) => await this.sources.get(name)!.load(this.view)),
    );
    if (this.disposed) {
      return;
    }
    this.openEvents();
    if (!loaded.every(Boolean)) {
      this.revealBlockedSource();
    }
  }

  async switchView(view: string): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    const transition = ++this.transition;
    if (!(await this.prepareViewChange()) || this.disposed || transition !== this.transition) {
      return false;
    }
    return await this.loadView(view, transition);
  }

  async prepareViewChange(): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    if (await this.flush()) {
      return true;
    }
    this.revealBlockedSource();
    return false;
  }

  cancelSwitch(): void {
    this.transition += 1;
    this.sources.forEach((source) => source.cancelLoad());
  }

  async flush(): Promise<boolean> {
    const results = await Promise.all(
      SOURCE_NAMES.map(async (name) => await this.sources.get(name)!.save()),
    );
    return results.every(Boolean);
  }

  get hasPendingChanges(): boolean {
    return SOURCE_NAMES.some((name) => this.sources.get(name)?.hasPendingChanges);
  }

  activate(name: SourceName): void {
    this.setActive(name);
    this.publish();
  }

  edit(name: SourceName, content: string): void {
    this.contents.set(name, content);
    this.sources.get(name)?.edit(content);
  }

  save(name: SourceName): void {
    void this.sources.get(name)?.save();
  }

  useDisk(): void {
    this.sources.get(this.active)?.useDisk();
  }

  keepLocal(): void {
    void this.sources.get(this.active)?.keepLocal();
  }

  focusHtml(): void {
    this.setActive("index.html");
    this.focusRequest += 1;
    this.revealSource();
    this.publish();
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.transition += 1;
    this.events.close();
    this.sources.forEach((source) => source.dispose());
    this.listeners.clear();
  }

  private updateState(state: SourceState): void {
    this.states.set(state.name, state);
    if (state.phase === "conflict") {
      this.setActive(state.name);
      this.revealSource();
    }
    this.publish();
  }

  private revealBlockedSource(): void {
    const blocked = SOURCE_NAMES.find(
      (name) =>
        this.sources.get(name)?.hasConflict ||
        this.sources.get(name)?.hasPendingChanges ||
        this.states.get(name)?.phase === "error",
    );
    if (blocked) {
      this.activate(blocked);
      this.revealSource();
    }
  }

  private async loadView(view: string, transition: number): Promise<boolean> {
    this.sources.forEach((source) => source.beginLoad());
    const loaded = await Promise.allSettled(
      SOURCE_NAMES.map(async (name) => ({
        name,
        source: await this.sources.get(name)!.read(view),
      })),
    );
    if (transition !== this.transition) {
      return false;
    }
    if (this.hasPendingChanges) {
      this.sources.forEach((source) => source.cancelLoad());
      this.revealBlockedSource();
      return false;
    }
    let failed = false;
    for (const [index, result] of loaded.entries()) {
      const name = SOURCE_NAMES[index];
      if (result.status === "fulfilled") {
        this.sources.get(name)?.cancelLoad();
      } else {
        failed = true;
        this.sources.get(name)?.loadError(result.reason);
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
        this.sources.get(name)?.open(view, source);
      }
    }
    this.openEvents();
    this.publish();
    return true;
  }

  private openEvents(): void {
    if (this.disposed) {
      return;
    }
    this.events.open(
      appendUrlPath(this.supportUrl(this.view), "dev/events", globalThis.location.href),
      () => this.sources.forEach((source) => void source.reconcile()),
      ({ path, revision }) => {
        void this.sources.get(path)?.externalChange(revision);
      },
    );
  }

  private tabKey(view = this.view): string {
    return `${this.storagePrefix}:source:${view}`;
  }

  private setActive(name: SourceName): void {
    this.active = name;
    globalThis.localStorage.setItem(this.tabKey(), name);
  }

  private readActiveTab(view: string): SourceName {
    const stored = globalThis.localStorage.getItem(this.tabKey(view));
    return SOURCE_NAMES.find((name) => name === stored) ?? "index.html";
  }

  private publish(): void {
    if (this.disposed) {
      return;
    }
    this.updateSnapshot();
    this.listeners.forEach((listener) => listener());
  }

  private updateSnapshot(): void {
    this.snapshot = {
      view: this.view,
      active: this.active,
      focusRequest: this.focusRequest,
      documents: sourceRecord((name) => ({
        content: this.contents.get(name) ?? "",
        state: this.states.get(name) ?? { name, phase: "loading" },
      })),
    };
  }
}
