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
  const editorToPreview = (update: ControlUpdate) => {
    const translated = translate(update, editorCells, previewControls.cells);
    if (translated) {
      void preview.apply([translated]).catch((error: unknown) => {
        console.warn("Marimo preview control update failed", error);
      });
    }
  };
  const previewToEditor = (update: ControlUpdate) => {
    const translated = translate(update, previewCells, editorControls.cells);
    if (translated) {
      void editor.apply([translated]).catch((error: unknown) => {
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
    editor.dispose();
    preview.dispose();
  };
  const sync = { dispose };
  if (signal?.aborted) {
    dispose();
    return sync;
  }
  signal?.addEventListener("abort", dispose, { once: true });
  const initial = editor
    .snapshot()
    .map((update) => translate(update, editorCells, previewControls.cells))
    .filter((update): update is ControlUpdate => update !== undefined);
  try {
    await preview.apply(initial);
  } catch (error) {
    dispose();
    throw error;
  }
  return sync;
};
