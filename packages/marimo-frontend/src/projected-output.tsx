import type { CellId, UIElementId } from "@marimo-team/frontend/unstable_internal/core/cells/ids";
import type { CellOutput } from "@marimo-team/frontend/unstable_internal/core/kernel/messages";

import { cellDomProps } from "@marimo-team/frontend/unstable_internal/components/editor/common";
import { OutputArea } from "@marimo-team/frontend/unstable_internal/components/editor/Output";
import {
  notebookAtom,
  useNotebook,
} from "@marimo-team/frontend/unstable_internal/core/cells/cells";
import {
  createCell,
  createCellRuntimeState,
} from "@marimo-team/frontend/unstable_internal/core/cells/types";
import { UI_ELEMENT_REGISTRY } from "@marimo-team/frontend/unstable_internal/core/dom/uiregistry";
import { store } from "@marimo-team/frontend/unstable_internal/core/state/jotai";
import { VirtualFileTracker } from "@marimo-team/frontend/unstable_internal/core/static/virtual-file-tracker";
import { useLayoutEffect } from "react";

import { suppressReplacedControlValues } from "./embedded-control-state";
import { reconcileProjectedOutputState } from "./projected-output-state";

export interface MarimoCellOutputSnapshot {
  readonly channel: CellOutput["channel"];
  readonly mimetype: string;
  readonly data: EmbeddedJsonValue;
  readonly timestamp?: number;
}

export interface ProjectedOutputUpdate {
  ownerCellId: string;
  channel?: CellOutput["channel"];
  mimetype: string;
  data: EmbeddedJsonValue;
  timestamp: number;
  resetUiObjectIds: readonly string[];
}

const outputMimetypes = {
  "application/json": true,
  "application/vnd.jupyter.widget-view+json": true,
  "application/vnd.marimo+error": true,
  "application/vnd.marimo+mimebundle": true,
  "application/vnd.marimo+traceback": true,
  "application/vnd.vega.v5+json": true,
  "application/vnd.vega.v6+json": true,
  "application/vnd.vegalite.v5+json": true,
  "application/vnd.vegalite.v6+json": true,
  "image/avif": true,
  "image/bmp": true,
  "image/gif": true,
  "image/jpeg": true,
  "image/png": true,
  "image/svg+xml": true,
  "image/tiff": true,
  "text/csv": true,
  "text/html": true,
  "text/latex": true,
  "text/markdown": true,
  "text/password": true,
  "text/plain": true,
  "video/mp4": true,
  "video/mpeg": true,
} as const satisfies Record<CellOutput["mimetype"], true>;

const outputChannels = {
  "marimo-error": true,
  media: true,
  output: true,
  pdb: true,
  stderr: true,
  stdin: true,
  stdout: true,
} as const satisfies Record<CellOutput["channel"], true>;

const isCellId = (value: string): value is CellId => value.length > 0;

const parseCellId = (value: string): CellId => {
  if (!isCellId(value)) {
    throw new Error("A projected output owner must have a cell identifier");
  }
  return value;
};

const isOutputMimetype = (value: string): value is CellOutput["mimetype"] =>
  Object.hasOwn(outputMimetypes, value);

const isOutputChannel = (value: string): value is CellOutput["channel"] =>
  Object.hasOwn(outputChannels, value);

export const toMarimoCellOutput = (output: MarimoCellOutputSnapshot): CellOutput => {
  const channel: string = output.channel;
  if (!isOutputChannel(channel)) {
    throw new Error(`Marimo cannot render projected output channel ${channel}`);
  }
  if (!isOutputMimetype(output.mimetype)) {
    throw new Error(`Marimo cannot render projected output type ${output.mimetype}`);
  }
  const cellOutput: CellOutput = {
    channel,
    mimetype: output.mimetype,
    // SAFETY: Prepared data is JSON-validated and the matching Marimo MIME type is checked above.
    data: structuredClone(output.data) as CellOutput["data"],
  };
  if (output.timestamp !== undefined) {
    cellOutput.timestamp = output.timestamp;
  }
  return cellOutput;
};

const toCellOutput = (output: ProjectedOutputUpdate): CellOutput =>
  toMarimoCellOutput({
    channel: output.channel ?? "output",
    mimetype: output.mimetype,
    data: output.data,
    timestamp: output.timestamp,
  });

const ensureProjectedOutputOwner = (ownerCellId: CellId, executionTime: number): void => {
  store.set(notebookAtom, (state) => {
    if (
      Object.hasOwn(state.cellData, ownerCellId) &&
      Object.hasOwn(state.cellRuntime, ownerCellId)
    ) {
      return state;
    }
    return {
      ...state,
      cellData: {
        ...state.cellData,
        [ownerCellId]: createCell({
          id: ownerCellId,
          lastExecutionTime: executionTime,
        }),
      },
      cellRuntime: {
        ...state.cellRuntime,
        [ownerCellId]: createCellRuntimeState(),
      },
    };
  });
};

export const reconcileProjectedOutput = (output: ProjectedOutputUpdate): void => {
  const ownerCellId = parseCellId(output.ownerCellId);
  const cellOutput = toCellOutput(output);
  reconcileProjectedOutputState(
    output,
    UI_ELEMENT_REGISTRY.entries,
    () => VirtualFileTracker.INSTANCE.removeForCellId(ownerCellId),
    () =>
      VirtualFileTracker.INSTANCE.track({
        cell_id: ownerCellId,
        output: cellOutput,
      }),
    (objectIds) => suppressReplacedControlValues(UI_ELEMENT_REGISTRY, objectIds),
  );
};

export const releaseProjectedOutputResources = (
  ownerCellIdValue: string,
  resetUiObjectIds: readonly string[],
): void => {
  const ownerCellId = parseCellId(ownerCellIdValue);
  const ownerPrefix = `${ownerCellId}-`;
  if (resetUiObjectIds.some((objectId) => !objectId.startsWith(ownerPrefix))) {
    throw new Error("A projected output may reset only UI objects owned by its projection.");
  }
  resetUiObjectIds.forEach((objectId) =>
    // SAFETY: The owner-prefix check above establishes Marimo's UIElementId shape.
    UI_ELEMENT_REGISTRY.entries.delete(objectId as UIElementId),
  );
  VirtualFileTracker.INSTANCE.removeForCellId(ownerCellId);
};

const ownerReferences = new Map<CellId, number>();

const retainProjectedOutputOwner = (ownerCellId: CellId): void => {
  ownerReferences.set(ownerCellId, (ownerReferences.get(ownerCellId) ?? 0) + 1);
};

const releaseProjectedOutputOwner = (ownerCellId: CellId): void => {
  const references = ownerReferences.get(ownerCellId) ?? 0;
  if (references > 1) {
    ownerReferences.set(ownerCellId, references - 1);
    return;
  }
  ownerReferences.delete(ownerCellId);
  const state = store.get(notebookAtom);
  if (state.cellIds.inOrderIds.includes(ownerCellId)) {
    return;
  }
  VirtualFileTracker.INSTANCE.removeForCellId(ownerCellId);
  store.set(notebookAtom, (state) => {
    const cellData = { ...state.cellData };
    const cellRuntime = { ...state.cellRuntime };
    delete cellData[ownerCellId];
    delete cellRuntime[ownerCellId];
    return { ...state, cellData, cellRuntime };
  });
};

export const useProjectedOutputOwner = (ownerCellIdValue: string, timestamp: number): boolean => {
  const ownerCellId = parseCellId(ownerCellIdValue);
  const notebook = useNotebook();
  const registered =
    Object.hasOwn(notebook.cellData, ownerCellId) &&
    Object.hasOwn(notebook.cellRuntime, ownerCellId);

  useLayoutEffect(() => {
    retainProjectedOutputOwner(ownerCellId);
    return () => releaseProjectedOutputOwner(ownerCellId);
  }, [ownerCellId]);

  useLayoutEffect(() => {
    if (!registered) {
      ensureProjectedOutputOwner(ownerCellId, timestamp);
    }
  }, [timestamp, ownerCellId, registered]);

  return registered;
};

export const ProjectedOutputArea = ({
  accessibleName,
  output,
  stale,
}: {
  accessibleName?: string;
  output: ProjectedOutputUpdate;
  stale: boolean;
}) => {
  const ownerCellId = parseCellId(output.ownerCellId);
  const projectedOutput = toCellOutput(output);
  const registered = useProjectedOutputOwner(ownerCellId, output.timestamp);

  if (!registered) {
    return null;
  }

  return (
    <div
      aria-label={accessibleName}
      className="marimo"
      data-marimo-cell-output=""
      role="group"
      {...cellDomProps(ownerCellId, "_")}
    >
      <OutputArea
        allowExpand={false}
        cellId={ownerCellId}
        loading={false}
        output={projectedOutput}
        stale={stale}
      />
    </div>
  );
};
