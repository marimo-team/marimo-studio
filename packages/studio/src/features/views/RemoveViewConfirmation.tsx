import type { RefObject } from "react";

interface RemoveViewConfirmationProps {
  busy: boolean;
  confirmRef: RefObject<HTMLButtonElement | null>;
  error?: string;
  label: string;
  replacementDefault?: string;
  view: string;
  onCancel: () => void;
  onRemove: () => void;
}

export const RemoveViewConfirmation = ({
  busy,
  confirmRef,
  error,
  label,
  replacementDefault,
  view,
  onCancel,
  onRemove,
}: RemoveViewConfirmationProps) => (
  <section
    className="studio-remove-view-confirm"
    aria-labelledby="studio-remove-view-title"
    aria-busy={busy}
  >
    <strong id="studio-remove-view-title">Remove view?</strong>
    <p className="studio-remove-view-detail">
      This permanently deletes the <strong>{view}</strong> view and its files.
    </p>
    {replacementDefault ? (
      <p className="studio-remove-view-detail">
        <strong>{replacementDefault}</strong> will open at the notebook's main URL afterward.
      </p>
    ) : null}
    {error ? (
      <p className="studio-form-message" data-state="error" role="alert">
        {error}
      </p>
    ) : null}
    <div className="studio-form-actions">
      <button type="button" className="studio-control" disabled={busy} onClick={onCancel}>
        Cancel
      </button>
      <button
        ref={confirmRef}
        type="button"
        className="studio-control studio-danger-action"
        disabled={busy}
        onClick={onRemove}
      >
        {label}
      </button>
    </div>
  </section>
);
