import type { CellId } from "@marimo-team/frontend/unstable_internal/core/cells/ids";
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

import { reconcileProjectedOutputState } from "./projected-output-state";

export interface ProjectedOutputUpdate {
  ownerCellId: string;
  mimetype: string;
  data: string;
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

const isCellId = (value: string): value is CellId => value.length > 0;

const parseCellId = (value: string): CellId => {
  if (!isCellId(value)) {
    throw new Error("A projected output owner must have a cell identifier");
  }
  return value;
};

const isOutputMimetype = (value: string): value is CellOutput["mimetype"] =>
  Object.hasOwn(outputMimetypes, value);

const toCellOutput = (output: ProjectedOutputUpdate): CellOutput => {
  if (!isOutputMimetype(output.mimetype)) {
    throw new Error(`Marimo cannot render projected output type ${output.mimetype}`);
  }
  return {
    channel: "output",
    mimetype: output.mimetype,
    data: output.data,
    timestamp: output.timestamp,
  };
};

const ensureProjectedOutputOwner = (ownerCellId: CellId, executionTime: number): void => {
  store.set(notebookAtom, (state) => {
    if (state.cellData[ownerCellId] && state.cellRuntime[ownerCellId]) {
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
  );
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

export const ProjectedOutputArea = ({
  output,
  stale,
}: {
  output: ProjectedOutputUpdate;
  stale: boolean;
}) => {
  const ownerCellId = parseCellId(output.ownerCellId);
  const projectedOutput = toCellOutput(output);
  const notebook = useNotebook();
  const registered = Boolean(notebook.cellData[ownerCellId] && notebook.cellRuntime[ownerCellId]);

  useLayoutEffect(() => {
    retainProjectedOutputOwner(ownerCellId);
    return () => releaseProjectedOutputOwner(ownerCellId);
  }, [ownerCellId]);

  useLayoutEffect(() => {
    if (!registered) {
      ensureProjectedOutputOwner(ownerCellId, output.timestamp);
    }
  }, [output.timestamp, ownerCellId, registered]);

  if (!registered) {
    return null;
  }

  return (
    <div className="marimo" data-marimo-cell-output="" {...cellDomProps(ownerCellId, "_")}>
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
