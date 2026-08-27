import { useState } from "react";

import type { SourceConflict as Conflict } from "./remote.ts";

interface SourceConflictProps {
  conflict: Conflict;
  name: string;
  onKeepLocal: () => void;
  onUseDisk: () => void;
}

export const SourceConflict = ({ conflict, name, onKeepLocal, onUseDisk }: SourceConflictProps) => {
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const discardOnly = conflict.kind !== "revision";
  const message = {
    orphan: `${name} is no longer part of this view.`,
    "read-only": `${name} became read-only while you were editing.`,
    revision: `${name} changed on disk while you were editing.`,
  }[conflict.kind];
  return (
    <>
      <div className="studio-source-conflict" role="alert">
        <span>{message}</span>
        {conflict.externalRecovery ? (
          <span>
            Previous disk content is preserved at <code>{conflict.externalRecovery}</code>.
          </span>
        ) : null}
        <div>
          <button
            type="button"
            aria-controls="studio-source-comparison"
            aria-expanded={comparisonOpen}
            onClick={() => setComparisonOpen((open) => !open)}
          >
            Compare
          </button>
          <button type="button" onClick={onUseDisk}>
            {discardOnly ? "Discard edits" : "Use disk"}
          </button>
          {discardOnly ? null : (
            <button type="button" onClick={onKeepLocal}>
              Keep mine
            </button>
          )}
        </div>
      </div>

      {comparisonOpen ? (
        <div id="studio-source-comparison" className="studio-source-compare">
          <section>
            <strong>Your edits</strong>
            <pre>{conflict.local}</pre>
          </section>
          <section>
            <strong>{conflict.kind === "orphan" ? "Last on disk" : "On disk"}</strong>
            <pre>{conflict.remote.content}</pre>
          </section>
        </div>
      ) : null}
    </>
  );
};
