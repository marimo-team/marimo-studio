import type { SourceName } from "@marimo-studio/protocol/source-events";

import { errorMessage } from "../../shared/errors.ts";
import {
  type RemoteSource,
  RevisionConflict,
  type SourceConflict,
  type SourceRemote,
} from "./remote.ts";

export type SourcePhase = "loading" | "saved" | "saving" | "external" | "conflict" | "error";

export interface SourceState {
  name: SourceName;
  phase: SourcePhase;
  conflict?: SourceConflict;
  message?: string;
}

export interface SourceObserver {
  document(name: SourceName, content: string): void;
  state(state: SourceState): void;
}

export class SyncedSource {
  readonly name: SourceName;
  private view = "";
  private content = "";
  private revision = "";
  private dirty = false;
  private generation = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private conflict: SourceConflict | undefined;
  private write: Promise<boolean> | undefined;
  private writingContent: string | undefined;
  private state: SourceState;
  private loadState: SourceState | undefined;
  private sourceVersion = 0;
  private readGeneration = 0;

  constructor(
    name: SourceName,
    private readonly remote: SourceRemote,
    private readonly observer: SourceObserver,
    private readonly saveDelay = 350,
  ) {
    this.name = name;
    this.state = { name, phase: "loading" };
  }

  get hasConflict(): boolean {
    return this.conflict !== undefined;
  }

  get hasPendingChanges(): boolean {
    return this.dirty || this.conflict !== undefined;
  }

  beginLoad(): void {
    this.loadState ??= this.state;
    this.publish({ name: this.name, phase: "loading" });
  }

  cancelLoad(): void {
    const state = this.loadState;
    this.loadState = undefined;
    if (state) {
      this.publish(state);
    }
  }

  read(view: string): Promise<RemoteSource> {
    return this.remote.read(view, this.name);
  }

  open(view: string, source: RemoteSource): void {
    this.cancelSave();
    this.generation += 1;
    this.view = view;
    this.conflict = undefined;
    this.apply(source);
    this.emit("saved");
  }

  loadError(error: unknown): void {
    this.emit("error", errorMessage(error));
  }

  async load(view: string): Promise<boolean> {
    this.cancelSave();
    const generation = ++this.generation;
    this.view = view;
    this.content = "";
    this.revision = "";
    this.dirty = false;
    this.conflict = undefined;
    this.observer.document(this.name, "");
    this.emit("loading");
    try {
      const source = await this.remote.read(view, this.name);
      if (generation !== this.generation) {
        return false;
      }
      if (this.dirty) {
        if (source.content === this.content) {
          this.apply(source);
          this.emit("saved");
          return true;
        }
        this.conflict = { local: this.content, remote: source };
        this.cancelSave();
        this.emit("conflict");
        return false;
      }
      this.open(view, source);
      return true;
    } catch (error) {
      if (generation === this.generation) {
        this.emit("error", errorMessage(error));
      }
      return false;
    }
  }

  edit(content: string): void {
    if (content === this.content && !this.conflict) {
      return;
    }
    this.content = content;
    this.dirty = true;
    this.conflict = undefined;
    this.emit("saving");
    this.cancelSave();
    this.timer = setTimeout(() => void this.save(), this.saveDelay);
  }

  async save(): Promise<boolean> {
    this.cancelSave();
    if (this.write) {
      return await this.write;
    }
    const write = this.saveLatest();
    this.write = write;
    try {
      return await write;
    } finally {
      if (this.write === write) {
        this.write = undefined;
      }
    }
  }

  async externalChange(revision: string | null): Promise<void> {
    if (revision === null) {
      this.cancelSave();
      this.revision = "";
      this.sourceVersion += 1;
      this.conflict = undefined;
      if (!this.dirty) {
        this.content = "";
        this.observer.document(this.name, "");
      }
      this.emit("error", `${this.name} was deleted on disk. Restore it before saving in Studio.`);
      return;
    }
    if (revision === this.revision) {
      return;
    }
    await this.reconcile();
  }

  async reconcile(): Promise<void> {
    const generation = this.generation;
    const sourceVersion = this.sourceVersion;
    const readGeneration = ++this.readGeneration;
    try {
      const remote = await this.remote.read(this.view, this.name);
      if (
        generation !== this.generation ||
        sourceVersion !== this.sourceVersion ||
        readGeneration !== this.readGeneration ||
        remote.revision === this.revision
      ) {
        return;
      }
      if (this.dirty) {
        if (remote.content === this.content) {
          this.apply(remote);
          this.emit("saved");
          return;
        }
        if (remote.content === this.writingContent) {
          this.revision = remote.revision;
          this.sourceVersion += 1;
          this.emit("saving");
          return;
        }
        this.conflict = { local: this.content, remote };
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
        this.emit("error", errorMessage(error));
      }
    }
  }

  useDisk(): void {
    if (!this.conflict) {
      return;
    }
    this.apply(this.conflict.remote);
    this.conflict = undefined;
    this.dirty = false;
    this.emit("saved");
  }

  async keepLocal(): Promise<boolean> {
    if (!this.conflict) {
      return true;
    }
    this.revision = this.conflict.remote.revision;
    this.sourceVersion += 1;
    this.conflict = undefined;
    this.dirty = true;
    return await this.save();
  }

  dispose(): void {
    this.generation += 1;
    this.cancelSave();
  }

  private async saveLatest(): Promise<boolean> {
    while (this.dirty) {
      this.cancelSave();
      if (this.conflict) {
        return false;
      }
      if (!this.revision) {
        this.emit("error", `${this.name} cannot be saved until its source is available.`);
        return false;
      }
      const generation = this.generation;
      const view = this.view;
      const content = this.content;
      const revision = this.revision;
      this.writingContent = content;
      this.emit("saving");
      try {
        const next = await this.remote.write(view, this.name, content, revision);
        if (generation !== this.generation) {
          return false;
        }
        this.revision = next;
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
        if (error instanceof RevisionConflict) {
          return await this.loadConflict(generation);
        }
        this.emit("error", errorMessage(error));
        return false;
      } finally {
        if (this.writingContent === content) {
          this.writingContent = undefined;
        }
      }
    }
    return !this.conflict;
  }

  private async loadConflict(generation: number): Promise<boolean> {
    const sourceVersion = this.sourceVersion;
    const readGeneration = ++this.readGeneration;
    try {
      const remote = await this.remote.read(this.view, this.name);
      if (
        generation !== this.generation ||
        sourceVersion !== this.sourceVersion ||
        readGeneration !== this.readGeneration
      ) {
        return false;
      }
      if (remote.content === this.content) {
        this.apply(remote);
        this.conflict = undefined;
        this.emit("saved");
        return true;
      }
      this.conflict = { local: this.content, remote };
      this.emit("conflict");
      return false;
    } catch (error) {
      if (
        generation === this.generation &&
        sourceVersion === this.sourceVersion &&
        readGeneration === this.readGeneration
      ) {
        this.emit("error", errorMessage(error));
      }
      return false;
    }
  }

  private apply(source: RemoteSource): void {
    this.content = source.content;
    this.revision = source.revision;
    this.sourceVersion += 1;
    this.dirty = false;
    this.observer.document(this.name, source.content);
  }

  private emit(phase: SourcePhase, message?: string): void {
    this.loadState = undefined;
    this.publish({
      name: this.name,
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
