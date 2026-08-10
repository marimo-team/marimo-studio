import { useLayoutEffect } from "react";
import { createPortal } from "react-dom";

import type { MarimoOutputElement } from "../../outputs/host";

import { setOutputHostState } from "../../outputs/host";

export const DuplicateOutputPortal = ({ host }: { host: MarimoOutputElement }) => {
  useLayoutEffect(() => {
    const message = `Output ${JSON.stringify(host.valueSelector)} is mounted twice.`;
    const hint = "Keep one host for each projected output.";
    host.dataset.marimoSelector = host.valueSelector;
    delete host.dataset.marimoVariable;
    delete host.dataset.runtimeCellId;
    delete host.dataset.outputMime;
    host.dataset.marimoDiagnosticCode = "duplicate-output-host";
    host.dataset.marimoDiagnosticMessage = message;
    host.dataset.marimoDiagnosticHint = hint;
    setOutputHostState(host, "error", {
      selector: host.valueSelector,
      code: "duplicate-output-host",
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
      Output <code>{host.valueSelector}</code> is already mounted.
    </div>,
    host,
  );
};
