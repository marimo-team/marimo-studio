import type { SourceState } from "./sync.ts";

import { useSourceStatus } from "./useSourceStatus.ts";

export const SourceStatus = ({ state }: { state: SourceState }) => {
  const status = useSourceStatus(state);
  return (
    <span className="studio-source-status" data-state={status.phase} role="status">
      {status.message}
    </span>
  );
};
