import { useLayoutEffect } from "react";
import { createPortal } from "react-dom";

import type { MarimoCellElement } from "../../cells/host";

import { setCellHostState } from "../../cells/host";

export const DuplicateCellPortal = ({ host }: { host: MarimoCellElement }) => {
  useLayoutEffect(() => {
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
      delete host.dataset.marimoDiagnosticCode;
      delete host.dataset.marimoDiagnosticMessage;
      delete host.dataset.marimoDiagnosticHint;
    };
  }, [host]);

  return createPortal(
    <div className="marimo-cell-error" role="alert">
      Cell alias <code>{host.cellName}</code> is already mounted.
    </div>,
    host,
  );
};
