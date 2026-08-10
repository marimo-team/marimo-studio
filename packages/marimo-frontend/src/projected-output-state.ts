interface ProjectedOutputUpdate {
  ownerCellId: string;
  mimetype: string;
  data: string;
  timestamp: number;
  resetUiObjectIds: readonly string[];
}

interface UIElementEntries {
  delete(objectId: string): boolean;
}

interface VirtualFileMessage {
  cell_id: string;
  output: {
    channel: "output";
    mimetype: string;
    data: string;
    timestamp: number;
  };
}

export const reconcileProjectedOutputState = (
  output: ProjectedOutputUpdate,
  entries: UIElementEntries,
  resetVirtualFiles: (ownerCellId: string) => void,
  trackVirtualFiles: (message: VirtualFileMessage) => void,
): void => {
  const ownerPrefix = `${output.ownerCellId}-`;
  if (output.resetUiObjectIds.some((objectId) => !objectId.startsWith(ownerPrefix))) {
    throw new Error("A projected output may reset only UI objects owned by its projection.");
  }

  for (const objectId of output.resetUiObjectIds) {
    entries.delete(objectId);
  }
  resetVirtualFiles(output.ownerCellId);
  trackVirtualFiles({
    cell_id: output.ownerCellId,
    output: {
      channel: "output",
      mimetype: output.mimetype,
      data: output.data,
      timestamp: output.timestamp,
    },
  });
};
