import type { PreviewStatus } from "../preview/status.ts";

import { Diagnostic } from "../../shared/ui/Diagnostic.tsx";

export const RuntimeStatus = ({ status }: { status: PreviewStatus }) => (
  <div
    className="studio-runtime-status"
    data-state={status.state}
    role="status"
    aria-label="Preview runtime status"
  >
    <div className="studio-runtime-status-summary">
      <strong>{status.message}</strong>
    </div>
    {status.diagnostics.length > 0 ? (
      <ul className="studio-runtime-diagnostics">
        {status.diagnostics.map((diagnostic, index) => (
          <li
            key={[
              diagnostic.code,
              diagnostic.target,
              diagnostic.source?.path,
              diagnostic.source?.line,
              diagnostic.source?.column,
              index,
            ].join(":")}
          >
            <Diagnostic diagnostic={diagnostic} />
          </li>
        ))}
      </ul>
    ) : null}
  </div>
);
