import type { PreviewFrameState } from "./controller.ts";

import { Diagnostic } from "../../shared/ui/Diagnostic.tsx";

export const PreviewStatusPanel = ({
  state,
  onRetry,
}: {
  state: PreviewFrameState;
  onRetry: () => void;
}) => {
  if (
    state.progress === null &&
    state.status.state !== "error" &&
    (state.rendered || state.status.state !== "loading")
  ) {
    return null;
  }
  const failed = state.progress === null && state.status.state === "error";
  const message = state.progress?.message ?? state.status.message;
  const heading = state.rendered ? "Updating preview" : "Preparing preview";
  const failureHeading = state.rendered ? "Preview could not update" : "Preview could not start";
  return (
    <div className="studio-preview-status-panel" data-rendered={state.rendered}>
      <div role={failed ? "alert" : "status"}>
        <div className="studio-preview-status-heading">
          {failed ? null : (
            <span
              role="progressbar"
              aria-label={message}
              aria-valuenow={state.progress?.completed}
              aria-valuemax={state.progress?.total}
            >
              <span className="studio-view-loading-indicator" aria-hidden="true" />
            </span>
          )}
          <strong>{failed ? failureHeading : heading}</strong>
        </div>
        {state.status.diagnostics.map((diagnostic, index) => (
          <Diagnostic
            key={`${diagnostic.code}:${diagnostic.target ?? ""}:${index}`}
            diagnostic={diagnostic}
          />
        ))}
        {failed && state.status.diagnostics.length === 0 ? <p>{message}</p> : null}
        {failed ? (
          <button type="button" className="studio-control" onClick={onRetry}>
            Retry preview
          </button>
        ) : (
          <>
            <p className="studio-preview-activity" title={message}>
              {message}
            </p>
            <p className="studio-preview-count">
              {state.progress?.total !== undefined
                ? `${state.progress.completed} of ${state.progress.total}`
                : "\u00a0"}
            </p>
          </>
        )}
      </div>
    </div>
  );
};
