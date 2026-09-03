import { useLayoutEffect } from "react";
import { createPortal } from "react-dom";

import type { MarimoCellElement } from "../../cells/host";
import type { ProjectionHostBinding } from "../../projections/resolution";

import { setCellHostState } from "../../cells/host";
import { applyProjectionMetadata, resetProjectionHostMetadata } from "../../projections/instances";

export const DuplicateCellPortal = ({
  host,
  binding,
}: {
  host: MarimoCellElement;
  binding: ProjectionHostBinding;
}) => {
  useLayoutEffect(() => {
    applyProjectionMetadata(host, binding.resolution, binding.projectionRevision);
    const message = `Cell ${JSON.stringify(host.cellName)} is mounted twice.`;
    const hint = "Keep one host for each projected cell.";
    host.dataset.marimoDiagnosticCode = "duplicate-cell-host";
    host.dataset.marimoDiagnosticMessage = message;
    host.dataset.marimoDiagnosticHint = hint;
    setCellHostState(host, "error", {
      alias: host.cellName,
      code: "duplicate-cell-host",
      message,
      hint,
    });
    return () => {
      resetProjectionHostMetadata(host);
    };
  }, [binding, host]);

  return createPortal(
    <div className="marimo-cell-error" role="alert">
      Cell alias <code>{host.cellName}</code> is already mounted.
    </div>,
    host,
  );
};
