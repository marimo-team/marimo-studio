import { useLayoutEffect } from "react";
import { createPortal } from "react-dom";

import type { MarimoOutputElement } from "../../outputs/host";
import type { ProjectionHostBinding } from "../../projections/resolution";

import { setOutputHostState } from "../../outputs/host";
import { applyProjectionMetadata, resetProjectionHostMetadata } from "../../projections/instances";
import { setProjectionRuntimeCell } from "../../projections/instances.ts";

export const DuplicateOutputPortal = ({
  binding,
  host,
}: {
  binding: ProjectionHostBinding;
  host: MarimoOutputElement;
}) => {
  useLayoutEffect(() => {
    applyProjectionMetadata(host, binding.resolution, binding.projectionRevision);
    const message = `Output ${JSON.stringify(host.valueSelector)} is mounted twice.`;
    const hint = "Keep one host for each projected output.";
    host.dataset.marimoSelector = host.valueSelector;
    delete host.dataset.marimoVariable;
    setProjectionRuntimeCell(host, undefined);
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
      resetProjectionHostMetadata(host);
    };
  }, [binding, host]);

  return createPortal(
    <div className="marimo-cell-error" role="alert">
      Output <code>{host.valueSelector}</code> is already mounted.
    </div>,
    host,
  );
};
