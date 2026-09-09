import type { SourceDocument, SourceDocumentPath } from "@marimo-studio/protocol/source-documents";

import { errorMessage } from "../../shared/errors.ts";
import {
  type RemoteSource,
  RevisionConflict,
  type SourceConflict,
  type SourceRemote,
  SourceUnavailable,
} from "./remote.ts";

export type SourcePhase = "loading" | "saved" | "saving" | "external" | "conflict" | "error";

export interface SourceState {
  path: SourceDocumentPath;
  phase: SourcePhase;
  conflict?: SourceConflict;
  message?: string;
}

export interface SourceObserver {
  document(path: SourceDocumentPath, content: string): void;
  state(state: SourceState): void;
}

let sourceIncarnationSequence = 0;

export class SyncedSource {
  readonly path: SourceDocumentPath;
  readonly incarnation = ++sourceIncarnationSequence;
  private documentSpec: SourceDocument;
  private view = "";
  private content = "";
  private revision = "";
  private dirty = false;
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private conflict: SourceConflict | undefined;
  private write: Promise<boolean> | undefined;
  private writingContent: string | undefined;
  private diskSource: RemoteSource | undefined;
  private state: SourceState;
  private loadState: SourceState | undefined;
  private sourceVersion = 0;
  private catalogGeneration = "";
  private viewGeneration = "";
  private readGeneration = 0;
  private accessGeneration = 0;
  private disposed = false;

  constructor(
    document: SourceDocument,
    private readonly remote: SourceRemote,
    private readonly observer: SourceObserver,
    private readonly saveDelay = 350,
  ) {
    this.path = document.path;
    this.documentSpec = document;
    this.state = { path: document.path, phase: "loading" };
  }

  get access(): SourceDocument["access"] {
    return this.documentSpec.access;
  }

  get isLoaded(): boolean {
    return this.diskSource !== undefined;
  }

  get replacementVersion(): number {
    return this.sourceVersion;
  }

  setOwner(catalogGeneration: string, viewGeneration: string): void {
    this.catalogGeneration = catalogGeneration;
    this.viewGeneration = viewGeneration;
  }

  async updateDocument(document: SourceDocument): Promise<void> {
    if (this.disposed) {
      return;
    }
    if (document.path !== this.path) {
      throw new TypeError("A synchronized source cannot change paths");
    }
    const becameReadOnly =
      this.documentSpec.access === "edit" && document.access === "read" && this.hasPendingChanges;
    const wasOrphaned = this.conflict?.kind === "orphan";
    const accessGeneration = ++this.accessGeneration;
    this.documentSpec = document;
    if (wasOrphaned && this.conflict) {
      this.conflict = {
        ...this.conflict,
        kind: document.access === "read" ? "read-only" : "revision",
      };
      this.emit("conflict");
      return;
    }
    if (!becameReadOnly) {
      return;
    }
    this.cancelSave();
    if (this.write) {
      await this.write;
    }
    if (this.disposed) {
      return;
    }
    if (accessGeneration !== this.accessGeneration || this.access !== "read") {
      return;
    }
    const generation = ++this.generation;
    try {
      const remote = await this.remote.read(this.view, this.path);
      if (generation !== this.generation || accessGeneration !== this.accessGeneration) {
        return;
      }
      if (remote.content === this.content) {
        this.conflict = undefined;
        this.apply(remote);
        this.emit("saved");
        return;
      }
      this.conflict = { kind: "read-only", local: this.content, remote };
      this.dirty = true;
      this.emit("conflict");
    } catch (error) {
      if (generation === this.generation && accessGeneration === this.accessGeneration) {
        this.loadError(error);
      }
    }
  }

  async orphan(): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    if (!this.hasPendingChanges) {
      return false;
    }
    if (this.conflict?.kind === "orphan") {
      return true;
    }
    const accessGeneration = ++this.accessGeneration;
    this.documentSpec = { ...this.documentSpec, access: "read" };
    this.cancelSave();
    if (this.write) {
      await this.write;
    }
    if (this.disposed) {
      return false;
    }
    if (accessGeneration !== this.accessGeneration || this.access !== "read") {
      return false;
    }
    if (!this.hasPendingChanges) {
      return false;
    }
    const generation = ++this.generation;
    try {
      const remote = await this.remote.read(this.view, this.path);
      if (generation !== this.generation || accessGeneration !== this.accessGeneration) {
        return false;
      }
      this.conflict = { kind: "orphan", local: this.content, remote };
      this.dirty = true;
      this.emit("conflict");
      return true;
    } catch (error) {
      if (generation === this.generation && accessGeneration === this.accessGeneration) {
        if (this.diskSource) {
          this.conflict = { kind: "orphan", local: this.content, remote: this.diskSource };
          this.dirty = true;
          this.emit("conflict");
          return true;
        }
        this.loadError(error);
      }
      return false;
    }
  }

  get hasConflict(): boolean {
    return this.conflict !== undefined;
  }

  get hasPendingChanges(): boolean {
    return this.dirty || this.conflict !== undefined;
  }

  beginLoad(): void {
    this.loadState ??= this.state;
    this.publish({ path: this.path, phase: "loading" });
  }

  cancelLoad(): void {
    const state = this.loadState;
    this.loadState = undefined;
    if (state) {
      this.publish(state);
    }
  }

  open(view: string, source: RemoteSource): void {
    if (this.disposed) {
      return;
    }
    this.cancelSave();
    this.generation += 1;
    this.view = view;
    this.conflict = undefined;
    this.apply(source);
    this.emit("saved");
  }

  loadError(cause: unknown): void {
    if (cause instanceof SourceUnavailable && this.diskSource) {
      this.markUnavailable(errorMessage(cause));
      return;
    }
    this.emit("error", errorMessage(cause));
  }

  async load(view: string): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    this.cancelSave();
    const generation = ++this.generation;
    this.view = view;
    this.content = "";
    this.revision = "";
    this.diskSource = undefined;
    this.dirty = false;
    this.conflict = undefined;
    this.observer.document(this.path, "");
    this.emit("loading");
    try {
      const source = await this.remote.read(view, this.path);
      if (generation !== this.generation) {
        return false;
      }
      if (this.dirty) {
        if (source.content === this.content) {
          this.apply(source);
          this.emit("saved");
          return true;
        }
        this.conflict = { kind: "revision", local: this.content, remote: source };
        this.cancelSave();
        this.emit("conflict");
        return false;
      }
      this.open(view, source);
      return true;
    } catch (error) {
      if (generation === this.generation) {
        this.loadError(error);
      }
      return false;
    }
  }

  edit(content: string): void {
    if (this.disposed || this.access === "read") {
      return;
    }
    if (content === this.content && !this.conflict) {
      return;
    }
    this.content = content;
    this.dirty = true;
    this.cancelSave();
    if (this.conflict?.kind === "unavailable") {
      this.conflict = { ...this.conflict, local: content };
      this.emit("conflict");
      return;
    }
    if (!this.revision && this.diskSource) {
      this.conflict = { kind: "unavailable", local: content, remote: this.diskSource };
      this.emit("conflict");
      return;
    }
    this.conflict = undefined;
    this.emit("saving");
    this.timer = setTimeout(() => void this.save(), this.saveDelay);
  }

  async save(): Promise<boolean> {
    if (this.disposed) {
      return false;
    }
    if (this.access === "read") {
      return !this.hasPendingChanges;
    }
    this.cancelSave();
    if (this.write) {
      return await this.write;
    }
    const write = this.saveLatest().finally(() => {
      if (this.write === write) {
        this.write = undefined;
      }
    });
    this.write = write;
    return await write;
  }

  async externalChange(revision: string | null): Promise<void> {
    if (this.disposed) {
      return;
    }
    if (revision === null) {
      this.markUnavailable(`${this.path} was deleted on disk. Restore it before saving in Studio.`);
      return;
    }
    if (!this.conflict && revision === this.revision) {
      return;
    }
    await this.reconcile();
  }

  async reconcile(): Promise<void> {
    if (this.disposed) {
      return;
    }
    const generation = this.generation;
    const sourceVersion = this.sourceVersion;
    const readGeneration = ++this.readGeneration;
    try {
      const remote = await this.remote.read(this.view, this.path);
      if (
        generation !== this.generation ||
        sourceVersion !== this.sourceVersion ||
        readGeneration !== this.readGeneration ||
        (!this.conflict && remote.revision === this.revision)
      ) {
        return;
      }
      if (this.conflict?.kind === "unavailable" && this.diskSource) {
        this.revision = this.diskSource.revision;
      }
      if (this.dirty) {
        if (this.access === "read") {
          this.conflict = { kind: "read-only", local: this.content, remote };
          this.cancelSave();
          this.emit("conflict");
          return;
        }
        if (remote.content === this.content) {
          this.apply(remote);
          this.emit("saved");
          return;
        }
        if (this.conflict?.kind !== "unavailable" && remote.content === this.writingContent) {
          this.revision = remote.revision;
          this.sourceVersion += 1;
          this.emit("saving");
          return;
        }
        this.conflict = { kind: "revision", local: this.content, remote };
        this.cancelSave();
        this.emit("conflict");
        return;
      }
      this.apply(remote);
      this.emit("external");
    } catch (error) {
      if (
        generation === this.generation &&
        sourceVersion === this.sourceVersion &&
        readGeneration === this.readGeneration
      ) {
        this.loadError(error);
      }
    }
  }

  useSavedVersion(): void {
    if (this.disposed || !this.conflict) {
      return;
    }
    if (this.conflict.kind === "unavailable") {
      this.dirty = false;
      this.conflict = undefined;
      this.markUnavailable(`${this.path} is unavailable. Restore access before saving in Studio.`);
      return;
    }
    this.apply(this.conflict.remote);
    this.emit("saved");
  }

  async overwriteSavedVersion(): Promise<boolean> {
    if (this.disposed || this.access === "read") {
      return false;
    }
    if (this.write) {
      await this.write;
    }
    if (this.disposed) {
      return false;
    }
    const conflict = this.conflict;
    if (conflict?.kind === "unavailable") {
      return false;
    }
    if (!conflict) {
      return this.dirty ? await this.save() : true;
    }
    this.revision = conflict.remote.revision;
    this.sourceVersion += 1;
    this.conflict = undefined;
    this.dirty = true;
    return await this.save();
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.generation += 1;
    this.accessGeneration += 1;
    this.cancelSave();
  }

  private async saveLatest(): Promise<boolean> {
    while (this.dirty) {
      this.cancelSave();
      if (this.access === "read") {
        return false;
      }
      if (this.conflict) {
        return false;
      }
      if (!this.revision) {
        this.emit("error", `${this.path} cannot be saved until its source is available.`);
        return false;
      }
      const generation = this.generation;
      const view = this.view;
      const content = this.content;
      const revision = this.revision;
      const sourceVersion = this.sourceVersion;
      this.writingContent = content;
      this.emit("saving");
      try {
        const next = await this.remote.write(
          view,
          this.path,
          content,
          revision,
          this.catalogGeneration,
          this.viewGeneration,
        );
        if (generation !== this.generation) {
          return false;
        }
        const ownWriteWasObserved = this.conflict === undefined && this.revision === next;
        if (
          this.conflict !== undefined ||
          (sourceVersion !== this.sourceVersion && !ownWriteWasObserved)
        ) {
          return !this.hasPendingChanges;
        }
        this.revision = next;
        this.diskSource = { content, revision: next };
        this.sourceVersion += 1;
        if (this.content === content) {
          this.dirty = false;
          this.emit("saved");
          return true;
        }
      } catch (error) {
        if (generation !== this.generation) {
          return false;
        }
        if (this.conflict !== undefined) {
          return !this.hasPendingChanges;
        }
        if (sourceVersion !== this.sourceVersion) {
          continue;
        }
        if (error instanceof RevisionConflict) {
          return await this.loadConflict(generation, error.externalRecovery);
        }
        this.loadError(error);
        return false;
      } finally {
        if (this.writingContent === content) {
          this.writingContent = undefined;
        }
      }
    }
    return !this.conflict;
  }

  private async loadConflict(generation: number, externalRecovery?: string): Promise<boolean> {
    const sourceVersion = this.sourceVersion;
    const readGeneration = ++this.readGeneration;
    try {
      const remote = await this.remote.read(this.view, this.path);
      if (
        generation !== this.generation ||
        sourceVersion !== this.sourceVersion ||
        readGeneration !== this.readGeneration
      ) {
        return false;
      }
      if (remote.content === this.content) {
        this.apply(remote);
        this.emit("saved");
        return true;
      }
      this.conflict = {
        kind: "revision",
        local: this.content,
        remote,
        externalRecovery,
      };
      this.emit("conflict");
      return false;
    } catch (error) {
      if (
        generation === this.generation &&
        sourceVersion === this.sourceVersion &&
        readGeneration === this.readGeneration
      ) {
        this.loadError(error);
      }
      return false;
    }
  }

  private apply(source: RemoteSource): void {
    if (source.catalogGeneration && source.viewGeneration) {
      this.setOwner(source.catalogGeneration, source.viewGeneration);
    }
    this.content = source.content;
    this.revision = source.revision;
    this.diskSource = source;
    this.sourceVersion += 1;
    this.conflict = undefined;
    this.dirty = false;
    this.observer.document(this.path, source.content);
  }

  private markUnavailable(message: string): void {
    this.cancelSave();
    this.revision = "";
    this.sourceVersion += 1;
    const saved = this.conflict?.remote ?? this.diskSource;
    if (this.dirty && saved) {
      this.conflict = { kind: "unavailable", local: this.content, remote: saved };
      this.emit("conflict", message);
      return;
    }
    this.conflict = undefined;
    if (!this.dirty) {
      this.content = "";
      this.observer.document(this.path, "");
    }
    this.emit("error", message);
  }

  private emit(phase: SourcePhase, message?: string): void {
    this.loadState = undefined;
    this.publish({
      path: this.path,
      phase,
      conflict: this.conflict,
      message,
    });
  }

  private publish(state: SourceState): void {
    this.state = state;
    this.observer.state(state);
  }

  private cancelSave(): void {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }
}
