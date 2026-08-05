import { Trash2Icon } from "lucide-react";

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
        onCancel={model.actions.cancelCreate}
        onNameChange={model.actions.setName}
        onSubmit={model.actions.submitCreate}
      />
    ),
    list: (
      <button
        ref={model.refs.newView}
        type="button"
        className="studio-menu-item studio-new-view"
        onClick={model.actions.beginCreate}
      >
        + New view
      </button>
    ),
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

  return (
    <details
      ref={model.refs.menu}
      className="studio-menu studio-view-menu"
      onToggle={(event) => model.actions.toggled(event.currentTarget.open)}
    >
      <summary
        ref={model.refs.trigger}
        className="studio-control studio-menu-trigger"
        aria-label="Select or manage a view"
      >
        <span>{model.snapshot.current}</span>
        <MenuChevron />
      </summary>
      <div className="studio-menu-popover">
        <strong className="studio-menu-heading">Views</strong>
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
                  onClick={() => model.actions.choose(view.name)}
                >
                  <span className="studio-menu-check" aria-hidden="true">
                    ✓
                  </span>
                  {view.name}
                </button>
                {model.canRemove ? (
                  <button
                    type="button"
                    className="studio-view-remove"
                    aria-label={`Remove ${view.name} view`}
                    title={`Remove ${view.name} view`}
                    disabled={model.snapshot.deleting}
                    onClick={(event) => model.actions.beginRemoval(view.name, event.currentTarget)}
                  >
                    <Trash2Icon className="studio-view-remove-icon" aria-hidden />
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
        {panels[model.panel]}
      </div>
    </details>
  );
};
