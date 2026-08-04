import { lazy, Suspense } from "react";

import type { SourceController } from "./controller.ts";

import { SOURCE_FILES } from "./files.ts";
import { SourceConflict } from "./SourceConflict.tsx";
import { SourceStatus } from "./SourceStatus.tsx";
import { useSourcePane } from "./useSourcePane.ts";

const SourceEditor = lazy(async () => ({
  default: (await import("./SourceEditor.tsx")).SourceEditor,
}));

interface SourcePaneProps {
  controller: SourceController;
  visible: boolean;
}

export const SourcePane = ({ controller, visible }: SourcePaneProps) => {
  const model = useSourcePane(controller, visible);
  const conflict = model.activeDocument.state.conflict;

  return (
    <>
      <header className="studio-pane-header studio-source-header">
        <div className="studio-source-tabs" role="tablist" aria-label="View source files">
          {SOURCE_FILES.map((file) => {
            const active = model.snapshot.active === file.name;
            return (
              <button
                key={file.name}
                ref={model.tabRef(file.name)}
                id={`studio-source-tab-${file.id}`}
                type="button"
                role="tab"
                data-state={model.snapshot.documents[file.name].state.phase}
                aria-selected={active}
                aria-controls={`studio-source-${file.id}`}
                tabIndex={active ? 0 : -1}
                onClick={() => model.selectTab(file.name)}
                onKeyDown={(event) => {
                  if (model.tabKeyDown(file.name, event.key)) {
                    event.preventDefault();
                  }
                }}
              >
                {file.name}
              </button>
            );
          })}
        </div>
        <div className="studio-source-meta">
          <SourceStatus state={model.activeDocument.state} />
        </div>
      </header>

      {conflict ? (
        <SourceConflict
          key={`${model.snapshot.view}:${model.snapshot.active}`}
          conflict={conflict}
          name={model.snapshot.active}
          onUseDisk={() => controller.useDisk()}
          onKeepLocal={() => controller.keepLocal()}
        />
      ) : null}

      <div className="studio-pane-content studio-source-content">
        {SOURCE_FILES.map((file) => {
          const active = model.snapshot.active === file.name;
          const actions = model.editorActions[file.name];
          return (
            <div
              key={file.name}
              id={`studio-source-${file.id}`}
              className="studio-source-editor"
              role="tabpanel"
              aria-labelledby={`studio-source-tab-${file.id}`}
              hidden={!active}
            >
              <Suspense fallback={<div className="studio-source-loading">Opening editor</div>}>
                <SourceEditor
                  key={`${model.snapshot.view}:${file.name}`}
                  ref={model.editorRefs[file.name]}
                  active={visible && active}
                  language={file.language}
                  value={model.snapshot.documents[file.name].content}
                  onChange={actions.change}
                  onSave={actions.save}
                />
              </Suspense>
            </div>
          );
        })}
      </div>
    </>
  );
};
