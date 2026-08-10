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

interface ProjectedOutputUpdate {
  ownerCellId: string;
  mimetype: string;
  data: string;
  timestamp: number;
  resetUiObjectIds: readonly string[];
}

export const ensureProjectedOutputOwner = (ownerCellId: CellId, executionTime: number): void => {
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

const releaseProjectedOutputOwner = (ownerCellId: CellId): void => {
  store.set(notebookAtom, (state) => {
    if (state.cellIds.inOrderIds.includes(ownerCellId)) {
      return state;
    }
    const cellData = { ...state.cellData };
    const cellRuntime = { ...state.cellRuntime };
    delete cellData[ownerCellId];
    delete cellRuntime[ownerCellId];
    return { ...state, cellData, cellRuntime };
  });
};

export const ProjectedOutputArea = ({
  executionTime,
  ownerCellId,
  output,
  stale,
}: {
  executionTime: number;
  ownerCellId: CellId;
  output: CellOutput;
  stale: boolean;
}) => {
  const notebook = useNotebook();
  const registered = Boolean(notebook.cellData[ownerCellId] && notebook.cellRuntime[ownerCellId]);

  useLayoutEffect(() => {
    if (!registered) {
      ensureProjectedOutputOwner(ownerCellId, executionTime);
    }
  }, [executionTime, ownerCellId, registered]);

  useLayoutEffect(() => () => releaseProjectedOutputOwner(ownerCellId), [ownerCellId]);

  if (!registered) {
    return null;
  }

  return (
    <div className="marimo" data-marimo-cell-output="" {...cellDomProps(ownerCellId, "_")}>
      <OutputArea
        allowExpand={false}
        cellId={ownerCellId}
        loading={false}
        output={output}
        stale={stale}
      />
    </div>
  );
};
