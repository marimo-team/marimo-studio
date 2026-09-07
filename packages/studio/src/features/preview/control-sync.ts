import type { ControlBindings } from "@marimo-studio/protocol/frame-bridge";

import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";

export interface RuntimeCellMap {
  cells: Readonly<Record<string, string>>;
  bindings?: ControlBindings;
}

export interface ControlUpdate {
  objectId: string;
  value: unknown;
  origin?: "input" | "registration";
}

export interface ControlEndpoint {
  metadata?(): RuntimeCellMap | null | undefined;
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
  sourceBindings?: ControlBindings,
  targetBindings?: ControlBindings,
): ControlUpdate[] => {
  const value = jsonValueSchema.safeParse(update.value);
  if (!value.success) {
    return [];
  }
  if (sourceBindings !== undefined && targetBindings !== undefined) {
    const binding = Object.hasOwn(sourceBindings, update.objectId)
      ? sourceBindings[update.objectId]
      : undefined;
    if (!binding) {
      return [];
    }
    return Object.entries(targetBindings).flatMap(([objectId, candidate]) => {
      const matches =
        candidate.input === binding.input &&
        candidate.path.length === binding.path.length &&
        candidate.path.every((step, index) => {
          const expected = binding.path[index]!;
          return (
            step.kind === expected.kind &&
            (step.kind === "element" ||
              (expected.kind !== "element" && step.value === expected.value))
          );
        });
      return matches ? [{ objectId, value: value.data }] : [];
    });
  }
  const cell = source.find(({ runtime }) => update.objectId.startsWith(`${runtime}-`));
  const targetCell = cell && target[cell.semantic];
  return cell && targetCell
    ? [
        {
          objectId: `${targetCell}${update.objectId.slice(cell.runtime.length)}`,
          value: value.data,
        },
      ]
    : [];
};

export const synchronizeControlEndpoints = async ({
  editor,
  preview,
  editorControls,
  previewControls,
  signal,
  onStatus,
  previewBaseline,
}: {
  editor: ControlEndpoint;
  preview: ControlEndpoint;
  editorControls: RuntimeCellMap;
  previewControls: RuntimeCellMap;
  signal?: AbortSignal;
  onStatus?: (status: ControlSyncStatus) => void;
  previewBaseline?: {
    metadata: RuntimeCellMap;
    values: readonly ControlUpdate[];
    touched: ReadonlySet<string>;
  };
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
    if (update.origin === "registration") return;
    const translated = translate(
      update,
      editorCells,
      previewControls.cells,
      (editor.metadata?.() ?? editorControls).bindings,
      (preview.metadata?.() ?? previewControls).bindings,
    );
    void previewWriter.write(translated).catch(() => {});
  };
  const previewToEditor = (update: ControlUpdate) => {
    if (update.origin === "registration") return;
    const translated = translate(
      update,
      previewCells,
      editorControls.cells,
      (preview.metadata?.() ?? previewControls).bindings,
      (editor.metadata?.() ?? editorControls).bindings,
    );
    void editorWriter.write(translated).catch(() => {});
  };

  const stopEditor = editor.subscribe(editorToPreview);
  const stopPreview = preview.subscribe(previewToEditor);
  let disposed = false;
  const dispose = () => {
    if (disposed) {
      return;
    }
    disposed = true;
    signal?.removeEventListener("abort", dispose);
    stopEditor();
    stopPreview();
    editorWriter.dispose();
    previewWriter.dispose();
    editor.dispose();
    preview.dispose();
  };
  const sync = { dispose };
  if (signal?.aborted) {
    dispose();
    return sync;
  }
  const currentPreview = preview.snapshot();
  const currentPreviewMetadata = preview.metadata?.() ?? previewControls;
  const baseline = new Map<string, unknown>();
  const touched = new Set<string>();
  if (previewBaseline) {
    for (const update of previewBaseline.values) {
      for (const translated of translate(
        update,
        cellsByRuntimeId(previewBaseline.metadata),
        currentPreviewMetadata.cells,
        previewBaseline.metadata.bindings,
        currentPreviewMetadata.bindings,
      )) {
        baseline.set(translated.objectId, translated.value);
        if (previewBaseline.touched.has(update.objectId)) {
          touched.add(translated.objectId);
        }
      }
    }
  }
  const changedPreview = currentPreview.filter(
    (update) =>
      (touched.has(update.objectId) || previewBaseline?.touched.has(update.objectId)) &&
      JSON.stringify(baseline.get(update.objectId)) !== JSON.stringify(update.value),
  );
  const changedIds = new Set(changedPreview.map((update) => update.objectId));
  const previewSnapshot = new Map(currentPreview.map((update) => [update.objectId, update.value]));
  const initial: ControlUpdate[] = [];
  for (const update of editor.snapshot()) {
    for (const translated of translate(
      update,
      editorCells,
      previewControls.cells,
      (editor.metadata?.() ?? editorControls).bindings,
      currentPreviewMetadata.bindings,
    )) {
      if (
        !changedIds.has(translated.objectId) &&
        JSON.stringify(previewSnapshot.get(translated.objectId)) !==
          JSON.stringify(translated.value)
      ) {
        initial.push(translated);
      }
    }
  }
  const initialEditor = changedPreview.flatMap((update) =>
    translate(
      update,
      previewCells,
      editorControls.cells,
      currentPreviewMetadata.bindings,
      (editor.metadata?.() ?? editorControls).bindings,
    ),
  );
  const initialApply = abortable(
    Promise.all([previewWriter.write(initial), editorWriter.write(initialEditor)]),
    signal,
  );
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
