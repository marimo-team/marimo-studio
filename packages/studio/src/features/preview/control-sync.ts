import { jsonValueSchema, type RuntimeControls } from "@marimo-studio/protocol/runtime-config";

export interface ControlUpdate {
  objectId: string;
  value: unknown;
}

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

class ControlWriter {
  private readonly pending = new Map<string, ControlUpdate>();
  private readonly waiters: WriteWaiter[] = [];
  private version = 0;
  private pendingVersion = 0;
  private running = false;
  private disposed = false;

  constructor(private readonly endpoint: ControlEndpoint) {}

  write(updates: readonly ControlUpdate[]): Promise<void> {
    if (this.disposed || updates.length === 0) {
      return Promise.resolve();
    }
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
          this.settle(version, controlWriteError(cause));
          continue;
        }
        this.settle(version);
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
}

const cellsByRuntimeId = (controls: RuntimeControls): readonly CellIdentity[] =>
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
}: {
  editor: ControlEndpoint;
  preview: ControlEndpoint;
  editorControls: RuntimeControls;
  previewControls: RuntimeControls;
  signal?: AbortSignal;
}): Promise<ControlSync> => {
  const editorCells = cellsByRuntimeId(editorControls);
  const previewCells = cellsByRuntimeId(previewControls);
  const editorWriter = new ControlWriter(editor);
  const previewWriter = new ControlWriter(preview);
  const editorToPreview = (update: ControlUpdate) => {
    const translated = translate(update, editorCells, previewControls.cells);
    if (translated) {
      void previewWriter.write([translated]).catch((error) => {
        console.warn("Marimo preview control update failed", error);
      });
    }
  };
  const previewToEditor = (update: ControlUpdate) => {
    const translated = translate(update, previewCells, editorControls.cells);
    if (translated) {
      void editorWriter.write([translated]).catch((error) => {
        console.warn("Marimo editor control update failed", error);
      });
    }
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
  const initial = editor
    .snapshot()
    .map((update) => translate(update, editorCells, previewControls.cells))
    .filter((update): update is ControlUpdate => update !== undefined);
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
