import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";

export interface RuntimeCellMap {
  cells: Readonly<Record<string, string>>;
}

import type {
  ControlEndpoint,
  ControlEvent,
  ControlSource,
  ControlSync,
  ControlUpdate,
} from "./control-types.ts";

export interface ControlEndpoint {
  snapshot(): readonly ControlUpdate[];
  subscribe(listener: (update: ControlUpdate) => void): () => void;
  apply(updates: readonly ControlUpdate[]): Promise<void>;
  dispose(): void;
}

export type ControlFrameConnector = (frame: HTMLIFrameElement) => ControlEndpoint | undefined;

export interface ControlSync {
  dispose(): void;
}

export interface ControlSyncStatus {
  phase: "ready" | "degraded";
  error?: Error;
}

interface CellIdentity {
  semantic: string;
  runtime: string;
}

interface WriteWaiter {
  version: number;
  resolve: () => void;
  reject: (error: Error) => void;
}

const controlWriteError = (cause: unknown): Error =>
  cause instanceof Error ? cause : new Error(String(cause));
const CONTROL_RETRY_DELAYS = [100, 250, 500, 1_000, 2_000, 5_000] as const;

class ControlWriter {
  private readonly pending = new Map<string, ControlUpdate>();
  private readonly failed = new Map<string, ControlUpdate>();
  private readonly waiters: WriteWaiter[] = [];
  private version = 0;
  private pendingVersion = 0;
  private running = false;
  private disposed = false;
  private retryAttempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly endpoint: ControlEndpoint,
    private readonly failedWrite: (error: Error) => void,
    private readonly recovered: () => void,
  ) {}

  write(updates: readonly ControlUpdate[]): Promise<void> {
    if (this.disposed || updates.length === 0) {
      return Promise.resolve();
    }
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
    this.failed.forEach((update, objectId) => this.pending.set(objectId, update));
    this.failed.clear();
    this.retryAttempt = 0;
    const version = ++this.version;
    this.pendingVersion = version;
    updates.forEach((update) => this.pending.set(update.objectId, update));
    const applied = new Promise<void>((resolve, reject) => {
      this.waiters.push({ version, resolve, reject });
    });
    this.start();
    return applied;
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.pending.clear();
    this.failed.clear();
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
    this.waiters.splice(0).forEach(({ resolve }) => resolve());
  }

  private start(): void {
    if (this.running || this.disposed) {
      return;
    }
    this.running = true;
    void this.drain();
  }

  private async drain(): Promise<void> {
    try {
      while (!this.disposed && this.pending.size > 0) {
        const updates = Array.from(this.pending.values());
        const version = this.pendingVersion;
        this.pending.clear();
        try {
          await this.endpoint.apply(updates);
        } catch (cause) {
          const error = controlWriteError(cause);
          updates.forEach((update) => {
            if (!this.pending.has(update.objectId)) {
              this.failed.set(update.objectId, update);
            }
          });
          this.settle(version, error);
          this.failedWrite(error);
          this.scheduleRetry();
          continue;
        }
        this.retryAttempt = 0;
        this.settle(version);
        if (this.pending.size === 0 && this.failed.size === 0 && this.retryTimer === undefined) {
          this.recovered();
        }
      }
    } finally {
      this.running = false;
      if (!this.disposed && this.pending.size > 0) {
        this.start();
      }
    }
  }

  private settle(version: number, error?: Error): void {
    const settled = this.waiters.filter((waiter) => waiter.version <= version);
    this.waiters.splice(0, settled.length);
    settled.forEach((waiter) => {
      if (error === undefined) {
        waiter.resolve();
      } else {
        waiter.reject(error);
      }
    });
  }

  private scheduleRetry(): void {
    if (this.disposed || this.retryTimer !== undefined || this.failed.size === 0) {
      return;
    }
    const delay = CONTROL_RETRY_DELAYS[this.retryAttempt];
    if (delay === undefined) {
      return;
    }
    this.retryAttempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      this.failed.forEach((update, objectId) => {
        if (!this.pending.has(objectId)) {
          this.pending.set(objectId, update);
        }
      });
      this.failed.clear();
      this.start();
    }, delay);
  }
}

const cellsByRuntimeId = (controls: RuntimeCellMap): readonly CellIdentity[] =>
  Object.entries(controls.cells)
    .map(([semantic, runtime]) => ({ semantic, runtime }))
    .sort((left, right) => right.runtime.length - left.runtime.length);

const translate = (
  update: ControlUpdate,
  source: readonly CellIdentity[],
  target: Readonly<Record<string, string>>,
): ControlUpdate | undefined => {
  const cell = source.find(({ runtime }) => update.objectId.startsWith(`${runtime}-`));
  if (!cell) {
    return undefined;
  }
  const targetCell = target[cell.semantic];
  if (!targetCell) {
    return undefined;
  }
  const value = jsonValueSchema.safeParse(update.value);
  if (!value.success) {
    return undefined;
  }
  return {
    objectId: `${targetCell}${update.objectId.slice(cell.runtime.length)}`,
    value: value.data,
  };
};

export const synchronizeControlEndpoints = async ({
  editor,
  preview,
  editorControls,
  previewControls,
  signal,
  onStatus,
}: {
  editor: ControlEndpoint;
  preview: ControlEndpoint;
  editorControls: RuntimeCellMap;
  previewControls: RuntimeCellMap;
  signal?: AbortSignal;
  onStatus?: (status: ControlSyncStatus) => void;
}): Promise<ControlSync> => {
  const editorCells = cellsByRuntimeId(editorControls);
  const previewCells = cellsByRuntimeId(previewControls);
  const failures = new Set<"editor" | "preview">();
  const writer = (direction: "editor" | "preview", endpoint: ControlEndpoint) =>
    new ControlWriter(
      endpoint,
      (error) => {
        failures.add(direction);
        onStatus?.({ phase: "degraded", error });
      },
      () => {
        if (!failures.delete(direction)) {
          return;
        }
        if (failures.size === 0) {
          onStatus?.({ phase: "ready" });
        }
      },
    );
  const editorWriter = writer("editor", editor);
  const previewWriter = writer("preview", preview);
  const editorToPreview = (update: ControlUpdate) => {
    const translated = translate(update, editorCells, previewControls.cells);
    if (translated) {
      void previewWriter.write([translated]).catch(() => {});
    }
  };
  const previewToEditor = (update: ControlUpdate) => {
    const translated = translate(update, previewCells, editorControls.cells);
    if (translated) {
      void editorWriter.write([translated]).catch(() => {});
    }
    return pending.source === "editor"
      ? translation.editorFromBinding(pending.binding, pending.update)
      : translation.previewFromBinding(pending.binding, pending.update);
  };
  const retainUnmatched = (source: ControlSource): boolean =>
    structuredTranslation && source === "preview";
  const writer = (source: ControlSource): ControlWriter =>
    source === "editor" ? previewWriter : editorWriter;
  const sourceWriter = (source: ControlSource): ControlWriter =>
    source === "editor" ? editorWriter : previewWriter;
  const observeWrite = (source: ControlSource, operation: Promise<void>): void => {
    const observed = source === "editor" ? observedPreviewWrite : observedEditorWrite;
    if (observed === operation) {
      return;
    }
    if (source === "editor") {
      observedPreviewWrite = operation;
    } else {
      observedEditorWrite = operation;
    }
    void operation.then(
      () => {
        if (source === "editor" && observedPreviewWrite === operation) {
          observedPreviewWrite = undefined;
        }
        if (source === "preview" && observedEditorWrite === operation) {
          observedEditorWrite = undefined;
        }
      },
      (error: Error) => {
        if (source === "editor" && observedPreviewWrite === operation) {
          observedPreviewWrite = undefined;
        }
        if (source === "preview" && observedEditorWrite === operation) {
          observedEditorWrite = undefined;
        }
        if (!disposed) {
          quarantine(source);
          buffer.requireSnapshot(source, true);
        }
        console.warn("Marimo peer control update failed", error);
      },
    );
  };
  const route = (source: ControlSource, update: ControlEvent): void => {
    if (!sourceWriter(source).observe(update)) {
      return;
    }
    if (quarantined) {
      const value = jsonValueSchema.safeParse(update.value);
      if (value.success) {
        buffer.add(source, update, value.data, binding(source, update.objectId));
      }
      return;
    }
    const translated = translate(source, update);
    observeWrite(source, writer(source).write(translated));
  };
  const editorToPreview = (update: ControlEvent) => {
    route("editor", update);
  };
  const previewToEditor = (update: ControlEvent) => {
    route("preview", update);
  };

  const stopEditor = editor.subscribe(editorToPreview);
  const stopPreview = preview.subscribe(previewToEditor);
  const dispose = () => {
    if (disposed) {
      return;
    }
    disposed = true;
    const failures: unknown[] = [];
    const cleanup = (action: () => void): void => {
      try {
        action();
      } catch (error) {
        failures.push(error);
      }
    };
    signal?.removeEventListener("abort", dispose);
    buffer.clear();
    sources.clear();
    observedEditorWrite = undefined;
    observedPreviewWrite = undefined;
    cleanup(stopEditorTopology);
    cleanup(stopPreviewTopology);
    cleanup(stopEditor);
    cleanup(stopPreview);
    cleanup(() => editorWriter.dispose());
    cleanup(() => previewWriter.dispose());
    cleanup(() => editor.dispose());
    cleanup(() => preview.dispose());
    if (failures.length === 1) {
      throw failures[0];
    }
    if (failures.length > 1) {
      throw new AggregateError(failures, "Control synchronization cleanup failed");
    }
  };
  const endpointControls = (
    endpoint: ControlEndpoint,
    configured: RuntimeControls,
  ): RuntimeControls => {
    const bindings = endpoint.controlBindings?.();
    if (sources.size > 0) {
      if (bindings === undefined || configured.bindings === undefined) {
        return configured;
      }
      return runtimeControlsSchema.parse({
        bindings: Object.fromEntries([
          ...Object.entries(bindings),
          ...Object.entries(configured.bindings),
        ]),
      });
    }
    return bindings === undefined ? configured : runtimeControlsSchema.parse({ bindings });
  };
  const reconcileSnapshot = async (
    source: ControlSource,
    generation: number,
    snapshot: readonly ControlUpdate[],
  ): Promise<boolean | undefined> => {
    let chunk: ControlUpdate[] = [];
    let chunkBytes = 0;
    let complete = true;
    const flush = async (): Promise<void> => {
      if (chunk.length === 0) {
        return;
      }
      const current = chunk;
      chunk = [];
      chunkBytes = 0;
      await writer(source).write(current);
    };
    for (const update of snapshot) {
      if (generation !== topologyGeneration) {
        return undefined;
      }
      if (!jsonValueSchema.safeParse(update.value).success) {
        continue;
      }
      const translatedUpdates = translate(source, update);
      if (translatedUpdates.length === 0) {
        if (hasSource(source, update.objectId) && retainUnmatched(source)) {
          complete = false;
        }
        continue;
      }
      for (const translated of translatedUpdates) {
        const value = jsonValueSchema.safeParse(translated.value);
        if (!value.success) {
          continue;
        }
        const bytes = controlUpdateBytes(translated.objectId, value.data);
        if (
          chunk.length > 0 &&
          (chunk.length >= MAX_BUFFERED_CONTROLS || chunkBytes + bytes > MAX_BUFFERED_CONTROL_BYTES)
        ) {
          await flush();
        }
        chunk.push({ objectId: translated.objectId, value: structuredClone(value.data) });
        chunkBytes += bytes;
        if (chunk.length >= MAX_BUFFERED_CONTROLS || chunkBytes >= MAX_BUFFERED_CONTROL_BYTES) {
          await flush();
        }
      }
    }
    await flush();
    return generation === topologyGeneration ? complete : undefined;
  };
  const sync: ControlSync = {
    dispose,
    invalidateControls(source) {
      quarantine(source);
      if (source !== undefined) {
        buffer.requireSnapshot(source, true);
      }
    },
    isQuarantined: () => quarantined,
    quarantineVersion: () => topologyGeneration,
    quarantinedSources: () => new Set(sources),
    updateControls(controls = {}) {
      const update = controlUpdates.then(async () => {
        if (disposed) {
          return;
        }
        configuredEditorControls = controls.editor ?? configuredEditorControls;
        configuredPreviewControls = controls.preview ?? configuredPreviewControls;
        const nextEditorControls = endpointControls(editor, configuredEditorControls);
        const nextPreviewControls = endpointControls(preview, configuredPreviewControls);
        if (!controlContractsCompatible(nextEditorControls, nextPreviewControls)) {
          throw new Error("Control endpoints do not share a synchronization contract");
        }
        const nextTranslation = createControlTranslation(nextEditorControls, nextPreviewControls);
        const generation = topologyGeneration;
        translation = nextTranslation;
        structuredTranslation =
          nextEditorControls.bindings !== undefined && nextPreviewControls.bindings !== undefined;
        const pendingSources = buffer.snapshotSources();
        for (const source of pendingSources) {
          const endpoint = source === "editor" ? editor : preview;
          const snapshot = endpoint.snapshot();
          buffer.snapshotCaptured(source);
          let complete: boolean | undefined;
          try {
            complete = await reconcileSnapshot(source, generation, snapshot);
          } catch (error) {
            buffer.requireSnapshot(source, true);
            throw error;
          }
          if (complete === undefined) {
            buffer.requireSnapshot(source, true);
            return;
          }
          if (!complete) {
            buffer.requireSnapshot(source, true);
          }
        }

        const updateCount = buffer.updateCount();
        for (let index = 0; index < updateCount; index += 1) {
          if (generation !== topologyGeneration) {
            return;
          }
          const pending = buffer.takeOldest();
          if (pending === undefined) {
            break;
          }
          const translated = translateBuffered(pending);
          if (translated.length === 0) {
            if (
              (pending.binding !== undefined ||
                hasSource(pending.source, pending.update.objectId)) &&
              retainUnmatched(pending.source)
            ) {
              buffer.retain(pending);
            }
            continue;
          }
          try {
            await writer(pending.source).write(translated);
          } catch (error) {
            buffer.retain(pending);
            throw error;
          }
        }
        if (generation === topologyGeneration && !buffer.hasWork()) {
          quarantined = false;
          sources.clear();
        }
      });
      controlUpdates = update.catch(() => {});
      return update;
    },
  };
  if (signal?.aborted) {
    dispose();
    return sync;
  }
  const previewSnapshot = new Map(
    preview.snapshot().map((update) => [update.objectId, update.value]),
  );
  const initial = editor
    .snapshot()
    .map((update) => translate(update, editorCells, previewControls.cells))
    .filter(
      (update): update is ControlUpdate =>
        update !== undefined &&
        JSON.stringify(previewSnapshot.get(update.objectId)) !== JSON.stringify(update.value),
    );
  const initialApply = abortable(previewWriter.write(initial), signal);
  signal?.addEventListener("abort", dispose, { once: true });
  try {
    await initialApply;
  } catch (error) {
    dispose();
    throw error;
  }
  return sync;
};

const abortable = async <T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> => {
  if (!signal) {
    return await operation;
  }
  signal.throwIfAborted();
  let cancel = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    cancel = () => reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", cancel, { once: true });
  });
  try {
    return await Promise.race([operation, aborted]);
  } finally {
    signal.removeEventListener("abort", cancel);
  }
};
