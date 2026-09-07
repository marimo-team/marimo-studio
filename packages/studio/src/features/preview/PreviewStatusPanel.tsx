import type { PreviewFrameState } from "./controller.ts";

export const PreviewStatusPanel = ({
  state,
  onRetry,
}: {
  state: PreviewFrameState;
  onRetry: () => void;
}) => {
  if (
    state.progress === null &&
    (state.rendered || (state.status.state !== "loading" && state.status.state !== "error"))
  ) {
    return null;
  }
  const failed = state.progress === null && state.status.state === "error";
  const message = state.progress?.message ?? state.status.message;
  const heading = state.rendered ? "Updating preview" : "Preparing preview";
  return (
    <div className="studio-preview-status-panel" data-rendered={state.rendered}>
      <div role={failed ? "alert" : "status"}>
        <strong>{failed ? "Preview could not start" : heading}</strong>
        {state.status.diagnostics.map((diagnostic, index) => (
          <p key={index}>
            {diagnostic.message} {diagnostic.hint}
          </p>
        ))}
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
            <progress
              aria-label={message}
              value={state.progress?.completed}
              max={state.progress?.total}
            />
          </>
        )}
      </div>
    </div>
  );
};
