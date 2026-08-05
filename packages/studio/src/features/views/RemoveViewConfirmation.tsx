import type { RefObject } from "react";

interface RemoveViewConfirmationProps {
  busy: boolean;
  confirmRef: RefObject<HTMLButtonElement | null>;
  error?: string;
  label: string;
  view: string;
  onCancel: () => void;
  onRemove: () => void;
}

export const RemoveViewConfirmation = ({
  busy,
  confirmRef,
  error,
  label,
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
      This deletes the HTML, CSS, and static files for <strong>{view}</strong>.
    </p>
    {error ? (
      <p className="studio-form-message" data-state="error" role="alert">
        {error}
      </p>
    ) : null}
    <div className="studio-form-actions">
      <button type="button" className="studio-control" onClick={onCancel}>
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
