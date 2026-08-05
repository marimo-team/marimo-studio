import type { FormEventHandler, RefObject } from "react";

import type { ViewMessage } from "./controller.ts";

const MESSAGE_ROLES = {
  error: "alert",
  warning: "status",
} as const;

interface CreateViewFormProps {
  busy: boolean;
  inputRef: RefObject<HTMLInputElement | null>;
  message?: ViewMessage;
  name: string;
  submitLabel: string;
  onCancel: () => void;
  onNameChange: (name: string) => void;
  onSubmit: FormEventHandler;
}

export const CreateViewForm = ({
  busy,
  inputRef,
  message,
  name,
  submitLabel,
  onCancel,
  onNameChange,
  onSubmit,
}: CreateViewFormProps) => (
  <form className="studio-new-view-form" aria-busy={busy} onSubmit={onSubmit}>
    <label htmlFor="studio-view-name">New view</label>
    <input
      ref={inputRef}
      id="studio-view-name"
      name="name"
      type="text"
      autoComplete="off"
      autoCapitalize="none"
      spellCheck={false}
      pattern="[a-z][a-z0-9-]*"
      placeholder="executive-report"
      required
      value={name}
      onChange={(event) => onNameChange(event.target.value)}
    />
    <p className="studio-form-hint">
      Start with a lowercase letter. Use letters, numbers, and hyphens.
    </p>
    {message ? (
      <p
        className="studio-form-message"
        data-state={message.state}
        role={MESSAGE_ROLES[message.state]}
      >
        {message.text}
      </p>
    ) : null}
    <div className="studio-form-actions">
      <button type="button" className="studio-control" onClick={onCancel}>
        Cancel
      </button>
      <button type="submit" className="studio-control studio-primary-action" disabled={busy}>
        {submitLabel}
      </button>
    </div>
  </form>
);
