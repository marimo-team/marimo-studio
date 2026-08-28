import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";
import type { SourceFileChange } from "@marimo-studio/protocol/source-events";
import type { ViewProject } from "@marimo-studio/protocol/view-project";

import type { SourceRemote } from "./remote.ts";

import { errorMessage } from "../../shared/errors.ts";
import { createSourceRemote } from "./remote.ts";
import {
  type ProjectInspection,
  SourceSession,
  type SourceSnapshot,
  type SourceTargetDiagnostic,
} from "./session.ts";

export type { SourceDocumentSnapshot, SourceSnapshot } from "./session.ts";

type Listener = () => void;

interface LoadedSourceSession {
  session: SourceSession;
  loaded: boolean;
  persistedActive: boolean;
}

interface SourceSessionLoad {
  view: string;
  promise: Promise<void>;
}

interface SourceRefreshQueue {
  session: SourceSession;
  generation: number;
  full: boolean;
  changes: Map<SourceFileChange["path"], SourceFileChange["revision"]>;
  mutation: Promise<void>;
  retryAvailable: boolean;
}

interface ActiveSourceSelection {
  path: SourceDocumentPath | null;
  persisted: boolean;
}

export class SourceController {
  private readonly remote: SourceRemote;
  private readonly listeners = new Set<Listener>();
  private view: string;
  private session: SourceSession | undefined;
  private sessionLoad: SourceSessionLoad | undefined;
  private focusRequest = 0;
  private transition = 0;
  private started = false;
  private disposed = false;
  private snapshot: SourceSnapshot;
  private targetDiagnostic: SourceTargetDiagnostic | undefined;
  private refreshQueue: SourceRefreshQueue | undefined;
  private inspection: ProjectInspection = { phase: "checking" };

  constructor(
    private readonly supportUrl: (view: string) => string,
    serverToken: string,
    initialView: string,
    private readonly storagePrefix: string,
    private readonly revealSource: () => void,
    remote?: SourceRemote,
  ) {
    this.view = initialView;
    this.remote = remote ?? createSourceRemote(this.supportUrl, serverToken);
    this.snapshot = this.emptySnapshot();
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
    await this.loadCurrentSession();
  }

  selectView(view: string): void {
    if (this.disposed) {
      return;
    }
    if (view === this.view) {
      if (!this.session) {
        void this.loadCurrentSession();
      }
      return;
    }
    this.transition += 1;
    this.refreshQueue = undefined;
    this.session?.dispose();
    this.session = undefined;
    this.view = view;
    this.inspection = { phase: "checking" };
    this.targetDiagnostic = undefined;
    this.publish();
    if (this.started) {
      void this.loadCurrentSession();
    }
  }

  private loadCurrentSession(): Promise<void> {
    if (this.disposed || this.session?.view === this.view) {
      return Promise.resolve();
    }
    const view = this.view;
    const pending = this.sessionLoad;
    if (pending?.view === view) {
      return pending.promise;
    }
    const transition = ++this.transition;
    const promise = this.loadSelectedSession(view, transition);
    this.sessionLoad = { view, promise };
    void promise.finally(() => {
      if (this.sessionLoad?.promise === promise) {
        this.sessionLoad = undefined;
      }
    });
    return promise;
  }

  private async loadSelectedSession(view: string, transition: number): Promise<void> {
    let loadedSession: LoadedSourceSession;
    try {
      loadedSession = await this.loadSession(view);
    } catch (error) {
      if (!this.disposed && transition === this.transition) {
        this.failTarget(view, null, errorMessage(error));
      }
      return;
    }
    const { session, loaded, persistedActive } = loadedSession;
    if (this.disposed || transition !== this.transition) {
      session.dispose();
      return;
    }
    if (!loaded) {
      const failure = session.activeLoadFailure;
      const recovered = persistedActive && failure ? await session.loadNextReadable() : false;
      if (this.disposed || transition !== this.transition) {
        session.dispose();
        return;
      }
      if (recovered && failure) {
        this.commitSession(session, {
          view: session.view,
          path: failure.path,
          message: failure.message,
        });
        this.revealSource();
        return;
      }
      this.failSession(session);
      session.dispose();
      return;
    }
    this.commitSession(session);
    this.revealBlockedSource();
  }

  async prepareViewChange(): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    if ((await this.session?.flush()) ?? true) {
      return true;
    }
    this.revealBlockedSource();
    return false;
  }

  async flush(): Promise<boolean> {
    return (await this.session?.flush()) ?? true;
  }

  get hasPendingChanges(): boolean {
    return this.session?.hasPendingChanges ?? false;
  }

  activate(path: SourceDocumentPath): void {
    if (this.session?.activate(path)) {
      this.publish();
    }
  }

  edit(path: SourceDocumentPath, content: string): void {
    this.session?.edit(path, content);
  }

  save(path: SourceDocumentPath): void {
    this.session?.save(path);
  }

  useSavedVersion(): void {
    this.session?.useSavedVersion();
  }

  overwriteSavedVersion(): void {
    this.session?.overwriteSavedVersion();
  }

  focusSource(): void {
    if (this.session?.activePath === null) {
      this.session.activatePreferred();
    }
    this.focusRequest += 1;
    this.revealSource();
    this.publish();
  }

  reconcile(): void {
    void this.refreshProjectAndDocuments();
  }

  externalChanges(changes: readonly SourceFileChange[]): void {
    void this.refreshProjectAndDocuments(changes);
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.transition += 1;
    this.refreshQueue = undefined;
    this.session?.dispose();
    this.session = undefined;
    this.listeners.clear();
  }

  private async loadSession(view: string): Promise<LoadedSourceSession> {
    const project = await this.remote.project(view);
    const active = this.readActiveTab(project);
    let session!: SourceSession;
    session = this.createSession(project, active.path, () => this.session === session);
    const loaded = await session.load();
    return { session, loaded, persistedActive: active.persisted };
  }

  private createSession(
    project: ViewProject,
    active: SourceDocumentPath | null,
    current: () => boolean,
  ): SourceSession {
    return new SourceSession({
      active,
      changed: () => {
        if (current()) {
          this.publish();
        }
      },
      conflicted: () => {
        if (current()) {
          this.revealSource();
        }
      },
      persistActive: (path) => globalThis.localStorage.setItem(this.tabKey(project.view), path),
      project,
      remote: this.remote,
    });
  }

  private commitSession(session: SourceSession, targetDiagnostic?: SourceTargetDiagnostic): void {
    const previous = this.session;
    this.refreshQueue = undefined;
    this.session = session;
    this.view = session.view;
    this.inspection = { phase: "ready" };
    this.targetDiagnostic = targetDiagnostic;
    this.publish();
    if (previous && previous !== session) {
      previous.dispose();
    }
  }

  private revealBlockedSource(): void {
    const blocked = this.session?.blockedPath();
    if (!blocked) {
      return;
    }
    this.session?.activate(blocked);
    this.revealSource();
    this.publish();
  }

  private async refreshProjectAndDocuments(
    changes: readonly SourceFileChange[] = [],
  ): Promise<void> {
    const session = this.session;
    if (this.disposed) {
      return;
    }
    if (!session) {
      const view = this.view;
      await this.loadCurrentSession();
      if (this.disposed || this.view !== view) {
        return;
      }
      if (!this.session) {
        await Promise.resolve();
        await this.loadCurrentSession();
      }
      if (this.session?.view === view) {
        await this.refreshProjectAndDocuments(changes);
      }
      return;
    }
    const queue = this.refreshQueueFor(session);
    queue.retryAvailable = true;
    if (changes.length === 0) {
      queue.full = true;
    } else {
      for (const change of changes) {
        queue.changes.set(change.path, change.revision);
      }
    }
    await this.inspectProjectRefresh(queue);
  }

  private async inspectProjectRefresh(queue: SourceRefreshQueue): Promise<void> {
    const generation = ++queue.generation;
    if (this.isCurrentRefresh(queue, generation)) {
      this.inspection = { phase: "checking" };
      this.publish();
    }
    let project: ViewProject;
    try {
      project = await this.remote.project(queue.session.view);
    } catch (error) {
      await this.reportRefreshFailure(queue, generation, errorMessage(error));
      return;
    }
    await this.commitProjectRefresh(queue, generation, project);
  }

  private refreshQueueFor(session: SourceSession): SourceRefreshQueue {
    if (this.refreshQueue?.session === session) {
      return this.refreshQueue;
    }
    const queue: SourceRefreshQueue = {
      session,
      generation: 0,
      full: false,
      changes: new Map(),
      mutation: Promise.resolve(),
      retryAvailable: false,
    };
    this.refreshQueue = queue;
    return queue;
  }

  private commitProjectRefresh(
    queue: SourceRefreshQueue,
    generation: number,
    project: ViewProject,
  ): Promise<void> {
    const mutation = queue.mutation.then(async () => {
      if (!this.isCurrentRefresh(queue, generation) || project.view !== queue.session.view) {
        return;
      }
      const full = queue.full;
      const changes = [...queue.changes].map(([path, revision]) => ({ path, revision }));
      queue.full = false;
      queue.changes.clear();
      try {
        await queue.session.refresh(project, full ? [] : changes);
        if (this.isCurrentRefresh(queue, generation)) {
          this.inspection = { phase: "ready" };
          this.publish();
        }
      } catch (error) {
        if (full) {
          queue.full = true;
        }
        for (const change of changes) {
          if (!queue.changes.has(change.path)) {
            queue.changes.set(change.path, change.revision);
          }
        }
        if (this.isCurrentRefresh(queue, generation)) {
          this.inspection = {
            phase: "unavailable",
            message: errorMessage(error),
          };
          queue.session.loadError(error);
          this.publish();
        }
      }
    });
    queue.mutation = mutation;
    return mutation;
  }

  private reportRefreshFailure(
    queue: SourceRefreshQueue,
    generation: number,
    message: string,
  ): Promise<void> {
    let retry = false;
    const mutation = queue.mutation.then(() => {
      if (this.isCurrentRefresh(queue, generation)) {
        if (queue.retryAvailable && (queue.full || queue.changes.size > 0)) {
          queue.retryAvailable = false;
          retry = true;
        } else {
          this.inspection = { phase: "unavailable", message };
          this.publish();
        }
      }
    });
    queue.mutation = mutation;
    return mutation.then(async () => {
      if (retry) {
        await this.inspectProjectRefresh(queue);
      }
    });
  }

  private isCurrentRefresh(queue: SourceRefreshQueue, generation: number): boolean {
    return (
      !this.disposed &&
      this.refreshQueue === queue &&
      this.session === queue.session &&
      queue.generation === generation
    );
  }

  private tabKey(view = this.view): string {
    return `${this.storagePrefix}:source:${view}`;
  }

  private readActiveTab(project: ViewProject): ActiveSourceSelection {
    const stored = globalThis.localStorage.getItem(this.tabKey(project.view));
    const persisted = project.documents.find(({ path }) => path === stored)?.path;
    const path = persisted ?? SourceSession.preferredPath(project.documents);
    if (stored !== null && persisted === undefined) {
      if (path === null) {
        globalThis.localStorage.removeItem(this.tabKey(project.view));
      } else {
        globalThis.localStorage.setItem(this.tabKey(project.view), path);
      }
    }
    return {
      path,
      persisted: persisted !== undefined,
    };
  }

  private publish(): void {
    if (this.disposed) {
      return;
    }
    const sessionSnapshot = this.session?.snapshot(this.focusRequest, this.inspection);
    const target = this.targetDiagnostic;
    if (sessionSnapshot && target?.view === sessionSnapshot.view && target.path !== null) {
      const document = sessionSnapshot.documents.find(({ path }) => path === target.path);
      if (document === undefined || (document.loaded && document.state.phase !== "error")) {
        this.targetDiagnostic = undefined;
      }
    }
    this.snapshot = sessionSnapshot
      ? { ...sessionSnapshot, targetDiagnostic: this.targetDiagnostic }
      : {
          ...this.emptySnapshot(),
          phase: this.targetDiagnostic ? "error" : "loading",
          targetDiagnostic: this.targetDiagnostic,
        };
    this.listeners.forEach((listener) => listener());
  }

  private failSession(session: SourceSession): void {
    const failure = session.activeLoadFailure;
    this.failTarget(
      session.view,
      failure?.path ?? session.activePath,
      failure?.message ?? `Could not read the active source for ${session.view}`,
    );
  }

  private failTarget(view: string, path: SourceDocumentPath | null, message: string): void {
    this.targetDiagnostic = { view, path, message };
    this.revealSource();
    this.publish();
  }

  private emptySnapshot(): SourceSnapshot {
    return {
      phase: "loading",
      view: this.view,
      inspection: this.inspection,
      active: null,
      documents: [],
      focusRequest: this.focusRequest,
    };
  }
}
