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
  reconcileProjectedOutputState(
    output,
    UI_ELEMENT_REGISTRY.entries,
    (ownerCellId) => VirtualFileTracker.INSTANCE.removeForCellId(ownerCellId as CellId),
    (message) =>
      VirtualFileTracker.INSTANCE.track({
        cell_id: message.cell_id as CellId,
        output: message.output as CellOutput,
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
  const ownerCellId = output.ownerCellId as CellId;
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
        output={
          {
            channel: "output",
            mimetype: output.mimetype,
            data: output.data,
            timestamp: output.timestamp,
          } as CellOutput
        }
        stale={stale}
      />
    </div>
  );
};
