import { CheckIcon, PlusIcon, Trash2Icon } from "lucide-react";

import type { ViewController } from "./controller.ts";

import { MenuChevron } from "../../shared/ui/icons.tsx";
import { CreateViewForm } from "./CreateViewForm.tsx";
import { RemoveViewConfirmation } from "./RemoveViewConfirmation.tsx";
import { useViewMenu } from "./useViewMenu.ts";

export const ViewMenu = ({ controller }: { controller: ViewController }) => {
  const model = useViewMenu(controller);
  const panels = {
    create: (
      <CreateViewForm
        busy={model.snapshot.creating}
        inputRef={model.refs.input}
        message={model.snapshot.createMessage}
        name={model.name}
        submitLabel={model.createLabel}
        starter={model.starter}
        starterCatalog={model.snapshot.starterCatalog}
        starters={model.starters}
        onCancel={model.actions.cancelCreate}
        onNameChange={model.actions.setName}
        onRetryStarters={model.actions.retryStarters}
        onStarterChange={model.actions.setStarter}
        onSubmit={model.actions.submitCreate}
      />
    ),
    list: null,
    remove: model.snapshot.removing ? (
      <RemoveViewConfirmation
        busy={model.snapshot.deleting}
        confirmRef={model.refs.confirmRemoval}
        error={model.snapshot.removeError}
        label={model.removeLabel}
        view={model.snapshot.removing}
        onCancel={model.actions.cancelRemoval}
        onRemove={model.actions.remove}
      />
    ) : null,
  };
  const viewList = (
    <>
      <strong className="studio-menu-heading">Switch view</strong>
      <div className="studio-view-list" role="group" aria-label="Views">
        {model.rows.map((view) => {
          return (
            <div
              key={view.name}
              className="studio-view-row"
              data-removing={view.removing || undefined}
            >
              <button
                type="button"
                className="studio-menu-item studio-view-option"
                aria-current={view.current ? "page" : undefined}
                aria-busy={view.selecting || undefined}
                aria-label={view.selecting ? `${view.name}, loading` : undefined}
                onClick={() => model.actions.choose(view.name)}
              >
                {view.selecting ? (
                  <span className="studio-view-loading-indicator" aria-hidden="true" />
                ) : (
                  <CheckIcon className="studio-menu-check" strokeWidth={2} aria-hidden="true" />
                )}
                <span>{view.name}</span>
              </button>
              {model.canRemove ? (
                <button
                  type="button"
                  className="studio-view-remove"
                  data-view-remove={view.name}
                  aria-label={`Remove ${view.name} view`}
                  title={`Remove ${view.name} view`}
                  disabled={model.snapshot.deleting}
                  onClick={() => model.actions.beginRemoval(view.name)}
                >
                  <Trash2Icon className="studio-view-remove-icon" aria-hidden="true" />
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="studio-view-actions">
        <button
          ref={model.refs.newView}
          type="button"
          className="studio-menu-item studio-new-view"
          onClick={model.actions.beginCreate}
        >
          <PlusIcon className="studio-menu-item-icon" strokeWidth={1.75} aria-hidden="true" />
          <span>New view</span>
        </button>
      </div>
    </>
  );

  return (
    <>
      <details
        ref={model.refs.menu}
        className="studio-menu studio-view-menu"
        data-panel={model.panel}
        onToggle={(event) => model.actions.toggled(event.currentTarget.open)}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || model.snapshot.creating || model.snapshot.deleting) {
            return;
          }
          event.preventDefault();
          model.actions.closeMenu();
        }}
      >
        <summary
          ref={model.refs.trigger}
          className="studio-control studio-menu-trigger"
          aria-label={`Switch view: ${model.snapshot.current}`}
          aria-disabled={model.snapshot.creating || model.snapshot.deleting}
          onClick={(event) => {
            if (model.snapshot.creating || model.snapshot.deleting) {
              event.preventDefault();
            }
          }}
        >
          <span>{model.snapshot.current}</span>
          <MenuChevron />
        </summary>
        <div ref={model.refs.popover} className="studio-menu-popover" popover={model.popoverMode}>
          <div className="studio-view-menu-scroll">
            {model.panel === "list" ? viewList : panels[model.panel]}
          </div>
        </div>
      </details>
      {model.snapshot.selectionMessage ? (
        <div
          className="studio-view-selection-message"
          data-state={model.snapshot.selectionMessage.state}
          role="alert"
        >
          <span>{model.snapshot.selectionMessage.text}</span>
          <button type="button" onClick={() => controller.dismiss()}>
            Dismiss
          </button>
        </div>
      ) : null}
    </>
  );
};
