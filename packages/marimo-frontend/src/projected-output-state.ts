import type { EmbeddedJsonValue } from "./embedded-json.ts";

interface ProjectedOutputUpdate {
  ownerCellId: string;
  channel?: "marimo-error" | "media" | "output" | "pdb" | "stderr" | "stdin" | "stdout";
  mimetype: string;
  data: EmbeddedJsonValue;
  timestamp: number;
  resetUiObjectIds: readonly string[];
}

interface UIElementEntries {
  delete(objectId: string): boolean;
}

interface VirtualFileMessage {
  cell_id: string;
  output: {
    channel: "marimo-error" | "media" | "output" | "pdb" | "stderr" | "stdin" | "stdout";
    mimetype: string;
    data: EmbeddedJsonValue;
    timestamp: number;
  };
}

export const reconcileProjectedOutputState = (
  output: ProjectedOutputUpdate,
  entries: UIElementEntries,
  resetVirtualFiles: (ownerCellId: string) => void,
  trackVirtualFiles: (message: VirtualFileMessage) => void,
  prepareUiReset: (objectIds: readonly string[]) => void = () => {},
): void => {
  const ownerPrefix = `${output.ownerCellId}-`;
  if (output.resetUiObjectIds.some((objectId) => !objectId.startsWith(ownerPrefix))) {
    throw new Error("A projected output may reset only UI objects owned by its projection.");
  }

  prepareUiReset(output.resetUiObjectIds);
  for (const objectId of output.resetUiObjectIds) {
    entries.delete(objectId);
  }
  resetVirtualFiles(output.ownerCellId);
  trackVirtualFiles({
    cell_id: output.ownerCellId,
    output: {
      channel: output.channel ?? "output",
      mimetype: output.mimetype,
      data: output.data,
      timestamp: output.timestamp,
    },
  });
};
