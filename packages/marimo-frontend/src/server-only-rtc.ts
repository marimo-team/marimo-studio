import type { Extension } from "@codemirror/state";

import { atom } from "jotai";

import type { CellId } from "@/core/cells/ids";

// The output host runs in read mode. Keep editor collaboration disabled so
// Loro and its WASM runtime stay outside the packaged renderer graph.
export const connectedDocAtom = atom<"disabled" | undefined>("disabled");

export const realTimeCollaboration = (
  _cellId: CellId,
  _updateCellCode: (code: string) => void,
  initialCode = "",
): { extension: Extension; code: string } => ({
  code: initialCode,
  extension: [],
});
