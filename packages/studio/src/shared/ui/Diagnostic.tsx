import type { BrowserDiagnostic } from "@marimo-studio/protocol/runtime-status";

import { useState } from "react";

export const Diagnostic = ({ diagnostic }: { diagnostic: BrowserDiagnostic }) => {
  const [copyStatus, setCopyStatus] = useState<{ report: string; message: string } | null>(null);
  const report = JSON.stringify(diagnostic, null, 2);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopyStatus({ report, message: "Copied" });
    } catch {
      setCopyStatus({ report, message: "Select the technical details to copy them." });
    }
  };
  return (
    <div className="studio-diagnostic">
      <p className="studio-diagnostic-message">{diagnostic.message}</p>
      {diagnostic.target ? <code>{diagnostic.target}</code> : null}
      {diagnostic.source ? (
        <code>
          {diagnostic.source.path}:{diagnostic.source.line}:{diagnostic.source.column}
        </code>
      ) : null}
      <p className="studio-diagnostic-hint">
        <strong>What you can do</strong>
        {diagnostic.hint || "Review the technical details and server logs, then retry."}
      </p>
      <details className="studio-diagnostic-details">
        <summary>Technical details</summary>
        <pre tabIndex={0} aria-label="Diagnostic details">
          {report}
        </pre>
        <button type="button" className="studio-control" onClick={() => void copy()}>
          Copy diagnostic
        </button>
        <span role="status" className="studio-diagnostic-copy-status">
          {copyStatus?.report === report ? copyStatus.message : null}
        </span>
      </details>
    </div>
  );
};
