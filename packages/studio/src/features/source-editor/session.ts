import type { SourceDocument, SourceDocumentPath } from "@marimo-studio/protocol/source-documents";
import type { SourceFileChange } from "@marimo-studio/protocol/source-events";
import type {
  ProjectDiagnostic,
  PublishedArtifact,
  ViewBuildState,
  ViewProject,
} from "@marimo-studio/protocol/view-project";

import type { SourceRemote } from "./remote.ts";
import type { SourceState } from "./sync.ts";

import { SyncedSource } from "./sync.ts";

export interface SourceDocumentSnapshot extends SourceDocument {
  content: string;
  incarnation: number;
  loaded: boolean;
  replacementVersion: number;
  state: SourceState;
}

export interface SourceTargetDiagnostic {
  view: string;
  path: SourceDocumentPath | null;
  message: string;
}

export type ProjectInspection =
  | { phase: "checking" }
  | { phase: "ready" }
  | { phase: "unavailable"; message: string };

export interface SourceSnapshot {
  phase: "loading" | "ready" | "error";
  view: string;
  inspection: ProjectInspection;
  provider?: string;
  artifact?: PublishedArtifact | null;
  build?: ViewBuildState;
  diagnostics?: readonly ProjectDiagnostic[];
  active: SourceDocumentPath | null;
  documents: readonly SourceDocumentSnapshot[];
  focusRequest: number;
  targetDiagnostic?: SourceTargetDiagnostic;
}

interface SourceSessionOptions {
  active: SourceDocumentPath | null;
  changed: () => void;
  conflicted: () => void;
  persistActive: (path: SourceDocumentPath) => void;
  project: ViewProject;
  remote: SourceRemote;
}

export class SourceSession {
  readonly view: string;
  private project: ViewProject;
  private active: SourceDocumentPath | null;
  private order: SourceDocumentPath[] = [];
  private readonly documents = new Map<SourceDocumentPath, SourceDocument>();
  private readonly sources = new Map<SourceDocumentPath, SyncedSource>();
  private readonly contents = new Map<SourceDocumentPath, string>();
  private readonly states = new Map<SourceDocumentPath, SourceState>();
  private readonly loads = new Map<SourceDocumentPath, Promise<boolean>>();
  private readonly orphans = new Set<SourceDocumentPath>();
  private disposed = false;

  constructor(private readonly options: SourceSessionOptions) {
    this.project = options.project;
    this.view = options.project.view;
    this.active = options.active;
    for (const document of options.project.documents) {
      this.add(document);
    }
  }

  get activePath(): SourceDocumentPath | null {
    return this.active;
  }

  get hasPendingChanges(): boolean {
    return [...this.sources.values()].some((source) => source.hasPendingChanges);
  }

  async load(): Promise<boolean> {
    return this.active ? await this.loadPath(this.active) : true;
  }

  async loadNextReadable(): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    const failed = this.active;
    if (!failed) {
      return false;
    }
    const index = this.order.indexOf(failed);
    const candidates = [...this.order.slice(index + 1), ...this.order.slice(0, index)];
    for (const path of candidates) {
      this.setActive(path);
      const loaded = await this.loadPath(path);
      if (this.disposed) {
        return false;
      }
      if (loaded) {
        return true;
      }
    }
    this.setActive(failed);
    return false;
  }

  get activeLoadFailure(): Pick<SourceTargetDiagnostic, "path" | "message"> | undefined {
    if (!this.active) {
      return undefined;
    }
    const state = this.states.get(this.active);
    if (state?.phase !== "error") {
      return undefined;
    }
    return {
      path: this.active,
      message: state.message ?? `Could not read ${this.active}`,
    };
  }

  async flush(): Promise<boolean> {
    const results = await Promise.all(
      [...this.sources.values()].map(async (source) => await source.save()),
    );
    return results.every(Boolean);
  }

  activate(path: SourceDocumentPath): boolean {
    if (!this.documents.has(path)) {
      return false;
    }
    this.setActive(path);
    void this.loadPath(path);
    return true;
  }

  activatePreferred(): void {
    const path = SourceSession.preferredPath(this.project.documents);
    if (path) {
      this.setActive(path);
    }
  }

  edit(path: SourceDocumentPath, content: string): void {
    const source = this.sources.get(path);
    if (!source || source.access === "read" || !source.isLoaded) {
      return;
    }
    this.contents.set(path, content);
    source.edit(content);
  }

  save(path: SourceDocumentPath): void {
    void this.sources.get(path)?.save();
  }

  useSavedVersion(): void {
    const path = this.active;
    if (!path) {
      return;
    }
    const source = this.sources.get(path);
    source?.useSavedVersion();
    if (!this.orphans.has(path) || source?.hasPendingChanges) {
      return;
    }
    this.remove(path);
    const preferred = SourceSession.preferredPath(this.project.documents);
    this.active = preferred;
    if (preferred) {
      this.setActive(preferred);
      void this.loadPath(preferred);
    }
    this.options.changed();
  }

  overwriteSavedVersion(): void {
    if (this.active) {
      void this.sources.get(this.active)?.overwriteSavedVersion();
    }
  }

  blockedPath(): SourceDocumentPath | undefined {
    return this.order.find((path) => {
      const source = this.sources.get(path);
      return (
        source?.hasConflict || source?.hasPendingChanges || this.states.get(path)?.phase === "error"
      );
    });
  }

  async refresh(project: ViewProject, changes: readonly SourceFileChange[]): Promise<void> {
    if (this.disposed) {
      return;
    }
    const nextPaths = new Set(project.documents.map(({ path }) => path));
    const orphaning: Promise<boolean>[] = [];
    for (const [path, source] of this.sources) {
      if (nextPaths.has(path)) {
        this.orphans.delete(path);
        continue;
      }
      if (source.hasPendingChanges) {
        const document = this.documents.get(path);
        if (document) {
          this.documents.set(path, { ...document, access: "read" });
        }
        this.orphans.add(path);
        orphaning.push(source.orphan());
      } else {
        this.remove(path);
      }
    }
    const updates: Promise<void>[] = [];
    for (const document of project.documents) {
      const source = this.sources.get(document.path);
      if (source) {
        source.setOwner(project.catalog_generation, project.view_generation);
        this.documents.set(document.path, document);
        updates.push(source.updateDocument(document));
      } else {
        this.add(document);
      }
    }
    await Promise.all([...updates, ...orphaning]);
    if (this.disposed) {
      return;
    }
    const retained = this.order.filter(
      (path) => !nextPaths.has(path) && this.sources.get(path)?.hasPendingChanges,
    );
    this.order = [...project.documents.map(({ path }) => path), ...retained];
    this.project = project;
    if (this.active === null || !this.documents.has(this.active)) {
      const preferred = SourceSession.preferredPath(project.documents);
      this.active = preferred;
      if (preferred) {
        this.options.persistActive(preferred);
      }
    }
    this.options.changed();
    if (this.active) {
      await this.loadPath(this.active);
    }
    if (this.disposed) {
      return;
    }
    await Promise.all(
      changes.map(async ({ path, revision }) => {
        const source = this.sources.get(path);
        if (source?.isLoaded && !this.orphans.has(path)) {
          await source.externalChange(revision);
        }
      }),
    );
    if (this.disposed) {
      return;
    }
    if (changes.length === 0) {
      await Promise.all(
        [...this.sources.values()]
          .filter((source) => source.isLoaded && !this.orphans.has(source.path))
          .map(async (source) => await source.reconcile()),
      );
    }
  }

  loadError(cause: unknown): void {
    if (this.active) {
      this.sources.get(this.active)?.loadError(cause);
    }
  }

  snapshot(focusRequest: number, inspection: ProjectInspection): SourceSnapshot {
    return {
      phase: "ready",
      view: this.view,
      inspection,
      provider: this.project.provider,
      artifact: this.project.artifact,
      build: this.project.build,
      diagnostics: [...this.project.diagnostics, ...this.project.build.diagnostics],
      active: this.active,
      focusRequest,
      documents: this.order.flatMap((path) => {
        const document = this.documents.get(path);
        if (!document) {
          return [];
        }
        return [
          {
            ...document,
            content: this.contents.get(path) ?? "",
            incarnation: this.sources.get(path)?.incarnation ?? 0,
            loaded: this.sources.get(path)?.isLoaded ?? false,
            replacementVersion: this.sources.get(path)?.replacementVersion ?? 0,
            state: this.states.get(path) ?? { path, phase: "loading" },
          },
        ];
      }),
    };
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.loads.clear();
    this.orphans.clear();
    this.sources.forEach((source) => source.dispose());
  }

  static preferredPath(documents: readonly SourceDocument[]): SourceDocumentPath | null {
    return documents.find(({ access }) => access === "edit")?.path ?? documents.at(0)?.path ?? null;
  }

  private add(document: SourceDocument): SyncedSource {
    const source = new SyncedSource(document, this.options.remote, {
      document: (path, content) => {
        this.contents.set(path, content);
        this.options.changed();
      },
      state: (state) => {
        this.states.set(state.path, state);
        if (state.phase === "conflict") {
          this.setActive(state.path);
          this.options.conflicted();
        }
        this.options.changed();
      },
    });
    source.setOwner(this.project.catalog_generation, this.project.view_generation);
    this.order.push(document.path);
    this.documents.set(document.path, document);
    this.contents.set(document.path, "");
    this.states.set(document.path, { path: document.path, phase: "loading" });
    this.sources.set(document.path, source);
    return source;
  }

  private setActive(path: SourceDocumentPath): void {
    this.active = path;
    this.options.persistActive(path);
  }

  private loadPath(path: SourceDocumentPath): Promise<boolean> {
    if (this.disposed) {
      return Promise.resolve(false);
    }
    const source = this.sources.get(path);
    if (!source || source.isLoaded) {
      return Promise.resolve(source?.isLoaded ?? false);
    }
    const pending = this.loads.get(path);
    if (pending) {
      return pending;
    }
    const load = source.load(this.view);
    this.loads.set(path, load);
    void load.finally(() => {
      if (this.loads.get(path) === load) {
        this.loads.delete(path);
      }
    });
    return load;
  }

  private remove(path: SourceDocumentPath): void {
    this.sources.get(path)?.dispose();
    this.sources.delete(path);
    this.documents.delete(path);
    this.contents.delete(path);
    this.states.delete(path);
    this.loads.delete(path);
    this.orphans.delete(path);
    this.order = this.order.filter((candidate) => candidate !== path);
  }
}
