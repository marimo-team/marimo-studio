import type { PreviewStatus } from "../preview/status.ts";

export const RuntimeStatus = ({ status }: { status: PreviewStatus }) => (
  <div
    className="studio-runtime-status"
    data-state={status.state}
    title={status.title || undefined}
  >
    <span className="studio-runtime-dot" aria-hidden="true" />
    <span>{status.message}</span>
  </div>
);
