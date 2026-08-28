import type { Starter } from "@marimo-studio/protocol/provider-catalog";
import type { FormEventHandler, RefObject } from "react";

import type { StarterCatalogState } from "./catalog.ts";
import type { ViewMessage } from "./controller.ts";

import { StarterCatalogNotice } from "./StarterCatalogNotice.tsx";

const MESSAGE_ROLES = {
  error: "alert",
  warning: "status",
} as const;

const revealStarterOption = (input: HTMLInputElement): void => {
  const option = input.closest<HTMLElement>(".studio-starter-option");
  option?.scrollIntoView({ block: "nearest" });
};

interface CreateViewFormProps {
  busy: boolean;
  inputRef: RefObject<HTMLInputElement | null>;
  message?: ViewMessage;
  name: string;
  submitLabel: string;
  starter: string;
  starterCatalog: StarterCatalogState;
  starters: readonly Starter[];
  onCancel: () => void;
  onNameChange: (name: string) => void;
  onRetryStarters: () => void;
  onStarterChange: (starter: string) => void;
  onSubmit: FormEventHandler;
}

export const CreateViewForm = ({
  busy,
  inputRef,
  message,
  name,
  submitLabel,
  starter,
  starterCatalog,
  starters,
  onCancel,
  onNameChange,
  onRetryStarters,
  onStarterChange,
  onSubmit,
}: CreateViewFormProps) => {
  const selected = starters.find((candidate) => candidate.id === starter);
  return (
    <form className="studio-new-view-form" aria-busy={busy} onSubmit={onSubmit}>
      <label htmlFor="studio-view-name">New page</label>
      <input
        ref={inputRef}
        id="studio-view-name"
        name="name"
        type="text"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        aria-describedby="studio-view-name-hint"
        pattern="[a-z](?:[a-z0-9]|-)*"
        placeholder="executive-report"
        required
        disabled={busy}
        value={name}
        onChange={(event) => onNameChange(event.target.value)}
      />
      <p id="studio-view-name-hint" className="studio-form-hint">
        Start with a lowercase letter. Use letters, numbers, and hyphens.
      </p>
      <fieldset
        className="studio-starter-options"
        aria-busy={starterCatalog.phase === "loading"}
        disabled={busy}
      >
        <legend>Start with</legend>
        <StarterCatalogNotice
          catalog={starterCatalog}
          empty={starters.length === 0}
          onRetry={onRetryStarters}
        />
        {starters.map((candidate) => {
          const available = candidate.availability.available;
          return (
            <label
              key={candidate.id}
              className="studio-starter-option"
              data-selected={candidate.id === starter || undefined}
              data-available={available || undefined}
            >
              <input
                type="radio"
                name="starter"
                value={candidate.id}
                checked={candidate.id === starter}
                disabled={!available}
                onChange={() => onStarterChange(candidate.id)}
                onFocus={(event) => revealStarterOption(event.currentTarget)}
              />
              <span className="studio-starter-copy">
                <strong>{candidate.title}</strong>
                <span>{candidate.summary}</span>
                {!available ? (
                  <small className="studio-starter-action">
                    {candidate.availability.action ?? candidate.availability.reason}
                  </small>
                ) : null}
              </span>
            </label>
          );
        })}
      </fieldset>
      {selected ? (
        <details className="studio-starter-details">
          <summary>Files created</summary>
          <span>{selected.documents.join(", ")}</span>
        </details>
      ) : null}
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
        <button type="button" className="studio-control" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button
          type="submit"
          className="studio-control studio-primary-action"
          disabled={busy || selected?.availability.available !== true}
        >
          {submitLabel}
        </button>
      </div>
    </form>
  );
};
