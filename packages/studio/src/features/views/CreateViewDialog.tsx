import type { Starter } from "@marimo-studio/protocol/provider-catalog";

import { type HostPersistence, viewNameError } from "@marimo-studio/protocol/views";
import { XIcon } from "lucide-react";
import { type FormEvent, useEffect, useRef } from "react";

import type { StarterCatalogState } from "./catalog.ts";
import type { ViewMessage } from "./controller.ts";
import type { ViewDraftModel } from "./useViewDraft.ts";

import { StarterCatalogNotice } from "./StarterCatalogNotice.tsx";
import { persistenceNotice, StarterDetails } from "./StarterDetails.tsx";
import { StarterList } from "./StarterList.tsx";
import { ViewSettings } from "./ViewSettings.tsx";

const VIEW_NAME_PATTERN = "[a-z](?:[a-z0-9]|-)*";

const MESSAGE_ROLES = {
  error: "alert",
  warning: "status",
} as const;

export interface CreateViewDialogProps {
  open: boolean;
  busy: boolean;
  draft: ViewDraftModel;
  /** The notebook has no view yet, so the new view becomes its default. */
  firstView: boolean;
  starters: readonly Starter[];
  catalog: StarterCatalogState;
  viewRoot: string;
  persistence: HostPersistence;
  previewUrl: (starter: Starter) => string | undefined;
  message?: ViewMessage;
  submitLabel: string;
  onCancel: () => void;
  onRetryCatalog: () => void;
  onSubmit: (event: FormEvent) => void;
}

export const CreateViewDialog = ({
  open,
  busy,
  draft,
  firstView,
  starters,
  catalog,
  viewRoot,
  persistence,
  previewUrl,
  message,
  submitLabel,
  onCancel,
  onRetryCatalog,
  onSubmit,
}: CreateViewDialogProps) => {
  const dialog = useRef<HTMLDialogElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const selected = draft.selected;
  const folder = `${viewRoot || "views"}/${viewNameError(draft.value.name) ? "…" : draft.value.name}/`;

  useEffect(() => {
    const element = dialog.current;
    if (!element) {
      return;
    }
    if (open && !element.open) {
      element.showModal();
      nameInput.current?.focus();
      nameInput.current?.select();
    } else if (!open && element.open) {
      element.close();
    }
  }, [open]);

  // Keep the selected starter in view: the preselected one sorts anywhere in
  // the catalog, which can arrive after the dialog opens.
  const selectedId = selected?.id;
  useEffect(() => {
    if (!open || !selectedId) {
      return;
    }
    const frame = globalThis.requestAnimationFrame(() =>
      dialog.current
        ?.querySelector(".studio-starter-option[data-selected]")
        ?.scrollIntoView({ block: "nearest" }),
    );
    return () => globalThis.cancelAnimationFrame(frame);
  }, [open, selectedId]);

  return (
    <dialog
      ref={dialog}
      className="studio-create-view-dialog"
      aria-labelledby="studio-create-view-title"
      aria-describedby="studio-create-view-description"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) {
          onCancel();
        }
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) {
          onCancel();
        }
      }}
    >
      {open ? (
        <form className="studio-create-view-form" aria-busy={busy} onSubmit={onSubmit}>
          <header className="studio-create-view-header">
            <h2 id="studio-create-view-title">New view</h2>
            <p id="studio-create-view-description">
              Pick a starter. Studio copies its files into the view folder and builds the first
              preview.
            </p>
            <button
              type="button"
              className="studio-control studio-icon-button studio-dialog-close"
              aria-label="Close"
              disabled={busy}
              onClick={onCancel}
            >
              <XIcon className="studio-control-icon" aria-hidden="true" />
            </button>
          </header>
          <div className="studio-create-view-body">
            <StarterList
              starters={starters}
              selected={draft.value.starter}
              previewUrl={previewUrl}
              notice={
                <StarterCatalogNotice
                  catalog={catalog}
                  empty={starters.length === 0}
                  onRetry={onRetryCatalog}
                />
              }
              onSelect={(starter) => draft.update({ starter })}
            />
            <div className="studio-starter-pane">
              {selected ? (
                <div className="studio-starter-pane-content">
                  <StarterDetails
                    starter={selected}
                    previewUrl={previewUrl(selected)}
                    folder={folder}
                    persistence={persistence}
                  />
                  <ViewSettings
                    draft={draft}
                    starter={selected}
                    firstView={firstView}
                    busy={busy}
                  />
                </div>
              ) : null}
            </div>
          </div>
          <footer className="studio-create-view-footer">
            <div className="studio-view-name">
              <label htmlFor="studio-view-name">Name</label>
              <span className="studio-view-name-field">
                <span aria-hidden="true">{viewRoot ? `${viewRoot}/` : null}</span>
                <input
                  ref={nameInput}
                  id="studio-view-name"
                  name="name"
                  type="text"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  aria-describedby="studio-view-name-hint"
                  pattern={VIEW_NAME_PATTERN}
                  placeholder="executive-report"
                  required
                  disabled={busy}
                  value={draft.value.name}
                  onChange={(event) => draft.update({ name: event.target.value })}
                />
              </span>
            </div>
            {message ? (
              <p
                key="message"
                id="studio-view-name-hint"
                className="studio-form-message"
                data-state={message.state}
                role={MESSAGE_ROLES[message.state]}
              >
                {message.text}
              </p>
            ) : (
              <p key="hint" id="studio-view-name-hint" className="studio-form-hint">
                Lowercase letters, digits, and hyphens
              </p>
            )}
            <div className="studio-form-actions">
              <button type="button" className="studio-control" disabled={busy} onClick={onCancel}>
                Cancel
              </button>
              <button
                type="submit"
                className="studio-control studio-primary-action"
                aria-describedby={
                  persistenceNotice(persistence) ? "studio-view-persistence" : undefined
                }
                disabled={busy || selected?.availability.available !== true}
              >
                {submitLabel}
              </button>
            </div>
          </footer>
        </form>
      ) : null}
    </dialog>
  );
};
