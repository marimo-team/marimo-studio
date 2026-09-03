import { CheckIcon, PlusIcon, Trash2Icon } from "lucide-react";

import type { ViewController } from "./controller.ts";

import { MenuChevron } from "../../shared/ui/icons.tsx";
import { useDisclosureMenu } from "../../shared/useDisclosureMenu.ts";
import { CreateViewForm } from "./CreateViewForm.tsx";
import { RemoveViewConfirmation } from "./RemoveViewConfirmation.tsx";
import { useViewMenu } from "./useViewMenu.ts";

export const ViewMenu = ({ controller }: { controller: ViewController }) => {
  const model = useViewMenu(controller);
  const menu = useDisclosureMenu({
    detailsRef: model.refs.menu,
    dismissible: !model.snapshot.creating && !model.snapshot.deleting,
    onToggle: model.actions.toggled,
    triggerRef: model.refs.trigger,
  });
  const statusMessage = model.snapshot.removeMessage ?? model.snapshot.selectionMessage;
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
        replacementDefault={model.replacementDefault}
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
          const removeOwner =
            view.catalogGeneration && view.generation
              ? {
                  catalogGeneration: view.catalogGeneration,
                  generation: view.generation,
                }
              : undefined;
          let accessibleName = view.name;
          if (view.selecting) {
            accessibleName = `${view.name}, loading`;
          } else if (view.default) {
            accessibleName = `${view.name}, default`;
          }
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
                aria-label={accessibleName}
                onClick={() => model.actions.choose(view.name)}
              >
                {view.selecting ? (
                  <span className="studio-view-loading-indicator" aria-hidden="true" />
                ) : (
                  <CheckIcon className="studio-menu-check" strokeWidth={2} aria-hidden="true" />
                )}
                <span>{view.name}</span>
                {view.default ? <small className="studio-view-default">Default</small> : null}
              </button>
              {model.canRemove && removeOwner ? (
                <button
                  type="button"
                  className="studio-view-remove"
                  data-view-remove={view.name}
                  aria-label={`Remove ${view.name} view`}
                  title={`Remove ${view.name} view`}
                  disabled={model.snapshot.deleting}
                  onClick={() =>
                    model.actions.beginRemoval(
                      view.name,
                      removeOwner.catalogGeneration,
                      removeOwner.generation,
                    )
                  }
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
        ref={menu.detailsRef}
        className="studio-menu studio-view-menu"
        data-studio-disclosure-menu
        data-panel={model.panel}
        onToggle={menu.onToggle}
        onKeyDown={menu.onKeyDown}
      >
        <summary
          ref={menu.triggerRef}
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
      {statusMessage ? (
        <div
          className="studio-view-selection-message"
          data-state={statusMessage.state}
          role="alert"
        >
          <span>{statusMessage.text}</span>
          <button type="button" onClick={() => controller.dismiss()}>
            Dismiss
          </button>
        </div>
      ) : null}
    </>
  );
};
