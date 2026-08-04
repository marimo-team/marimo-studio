import type { SourceConflict as Conflict } from "./remote.ts";

import { useDisclosure } from "../hooks/useDisclosure.ts";

interface SourceConflictProps {
  conflict: Conflict;
  name: string;
  onKeepLocal: () => void;
  onUseDisk: () => void;
}

export const SourceConflict = ({ conflict, name, onKeepLocal, onUseDisk }: SourceConflictProps) => {
  const comparison = useDisclosure();
  return (
    <>
      <div className="studio-source-conflict" role="alert">
        <span>{name} changed on disk while you were editing.</span>
        <div>
          <button
            type="button"
            aria-controls="studio-source-comparison"
            aria-expanded={comparison.open}
            onClick={comparison.toggle}
          >
            Compare
          </button>
          <button type="button" onClick={onUseDisk}>
            Use disk
          </button>
          <button type="button" onClick={onKeepLocal}>
            Keep mine
          </button>
        </div>
      </div>

      {comparison.open ? (
        <div id="studio-source-comparison" className="studio-source-compare">
          <section>
            <strong>Your edits</strong>
            <pre>{conflict.local}</pre>
          </section>
          <section>
            <strong>On disk</strong>
            <pre>{conflict.remote.content}</pre>
          </section>
        </div>
      ) : null}
    </>
  );
};
