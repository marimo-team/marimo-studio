import type { ProjectDiagnostic } from "@marimo-studio/protocol/view-project";

import { lazy, Suspense } from "react";

import type { SourceController } from "./controller.ts";
import type { SourceDocumentSnapshot } from "./session.ts";

import { highestSeverityDiagnostic } from "./diagnostics.ts";
import { SourceConflict } from "./SourceConflict.tsx";
import { SourceProjectDetails } from "./SourceProjectDetails.tsx";
import { SourceStatus } from "./SourceStatus.tsx";
import { useSourcePane } from "./useSourcePane.ts";

const SourceEditor = lazy(async () => ({
  default: (await import("./SourceEditor.tsx")).SourceEditor,
}));

interface SourcePaneProps {
  controller: SourceController;
  visible: boolean;
}

const sourceTabDescription = (
  document: SourceDocumentSnapshot,
  diagnostic: ProjectDiagnostic | undefined,
): string => {
  const descriptions: string[] = [];
  const conflict = document.state.conflict;
  if (conflict) {
    descriptions.push(
      {
        orphan: "Conflict: removed from this view with unsaved edits",
        "read-only": "Conflict: became read-only while you were editing",
        revision: "Conflict: changed on disk while you were editing",
      }[conflict.kind],
    );
  } else if (document.state.phase === "error" && document.state.message) {
    descriptions.push(`Error: ${document.state.message}`);
  }
  if (diagnostic) {
    const severity = diagnostic.severity === "error" ? "Error" : "Warning";
    descriptions.push(`${severity}: ${diagnostic.message}`);
  }
  if (document.access === "read") {
    descriptions.push("Read-only");
  }
  return descriptions.join(". ");
};

export const SourcePane = ({ controller, visible }: SourcePaneProps) => {
  const model = useSourcePane(controller, visible);
  const active = model.activeDocument;
  const conflict = active?.state.conflict;
  const diagnostics = model.snapshot.diagnostics ?? [];
  const activeDiagnostic = active ? highestSeverityDiagnostic(diagnostics, active.path) : undefined;
  const diagnostic = activeDiagnostic ?? highestSeverityDiagnostic(diagnostics);
  const projectDiagnostic = highestSeverityDiagnostic(diagnostics);
  const build = model.snapshot.build;
  const artifact = model.snapshot.artifact;
  let sourceStatus = "No source documents";
  let emptySource = "This view has no source files to edit.";
  if (model.snapshot.phase === "loading") {
    sourceStatus = "Loading source documents";
    emptySource = "Loading source documents";
  } else if (model.snapshot.phase === "error") {
    sourceStatus = "Source unavailable";
    emptySource = "Source documents unavailable";
  }

  return (
    <>
      <header className="studio-pane-header studio-source-header">
        <div className="studio-source-header-row">
          <div className="studio-source-tabs" role="tablist" aria-label="View source files">
            {model.snapshot.documents.map((document, index) => {
              const selected = model.snapshot.active === document.path;
              const documentDiagnostic = highestSeverityDiagnostic(diagnostics, document.path);
              const tabId = `studio-source-tab-${index}`;
              const description = sourceTabDescription(document, documentDiagnostic);
              const descriptionId = `${tabId}-description`;
              const accessibleLabel =
                document.label && document.label !== document.path
                  ? `${document.label}, ${document.path}`
                  : document.path;
              return (
                <button
                  key={document.path}
                  ref={model.tabRef(document.path)}
                  id={tabId}
                  type="button"
                  className="studio-control"
                  role="tab"
                  data-access={document.access}
                  data-state={document.state.phase}
                  data-diagnostic={documentDiagnostic?.severity}
                  aria-selected={selected}
                  aria-controls="studio-source-editor-panel"
                  aria-label={accessibleLabel}
                  aria-describedby={description ? descriptionId : undefined}
                  tabIndex={selected ? 0 : -1}
                  title={document.path}
                  onClick={() => model.selectTab(document.path)}
                  onKeyDown={(event) => {
                    if (selected && event.key === "Tab" && !event.shiftKey) {
                      event.preventDefault();
                      model.focusEditor();
                      return;
                    }
                    if (model.tabKeyDown(document.path, event.key)) {
                      event.preventDefault();
                    }
                  }}
                >
                  <span>{document.label ?? document.path}</span>
                  {document.access === "read" ? (
                    <span className="studio-source-readonly" aria-hidden="true">
                      Read-only
                    </span>
                  ) : null}
                  {description ? (
                    <span id={descriptionId} className="studio-visually-hidden">
                      {description}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          <div className="studio-source-meta">
            {active ? (
              <SourceStatus state={active.state} />
            ) : (
              <span
                className="studio-source-status"
                role="status"
                aria-label="Source document status"
              >
                {sourceStatus}
              </span>
            )}
            {build ? (
              <SourceProjectDetails
                artifact={artifact}
                build={build}
                diagnostic={projectDiagnostic}
                inspection={model.snapshot.inspection}
              />
            ) : null}
          </div>
        </div>
      </header>

      {model.snapshot.targetDiagnostic ? (
        <div className="studio-source-diagnostic" data-severity="error" role="alert">
          <span>
            Could not open{" "}
            {model.snapshot.targetDiagnostic.view === model.snapshot.view &&
            model.snapshot.targetDiagnostic.path
              ? model.snapshot.targetDiagnostic.path
              : model.snapshot.targetDiagnostic.view}
            .
          </span>
          {model.snapshot.targetDiagnostic.view !== model.snapshot.view &&
          model.snapshot.targetDiagnostic.path ? (
            <code>{model.snapshot.targetDiagnostic.path}</code>
          ) : null}
          <small>{model.snapshot.targetDiagnostic.message}</small>
        </div>
      ) : null}

      {diagnostic ? (
        <div
          className="studio-source-diagnostic"
          data-severity={diagnostic.severity}
          role={diagnostic.severity === "error" ? "alert" : "status"}
        >
          <span>{diagnostic.message}</span>
          {diagnostic.source ? (
            <code>
              {diagnostic.source.path}:{diagnostic.source.line}:{diagnostic.source.column}
            </code>
          ) : null}
          {diagnostic.hint ? <small>{diagnostic.hint}</small> : null}
        </div>
      ) : null}

      {conflict && active ? (
        <SourceConflict
          key={`${model.snapshot.view}:${active.path}`}
          conflict={conflict}
          name={active.path}
          onUseSavedVersion={() => controller.useSavedVersion()}
          onOverwriteSavedVersion={() => controller.overwriteSavedVersion()}
        />
      ) : null}

      <div className="studio-pane-content studio-source-content">
        {active ? (
          <div
            id="studio-source-editor-panel"
            className="studio-source-editor"
            role="tabpanel"
            aria-labelledby={`studio-source-tab-${model.snapshot.documents.findIndex(
              ({ path }) => path === active.path,
            )}`}
          >
            <Suspense fallback={<div className="studio-source-loading">Opening editor</div>}>
              <SourceEditor
                ref={model.editorRef}
                active={visible}
                documentId={`${model.snapshot.view}:${active.path}`}
                incarnation={active.incarnation}
                label={`${active.path} source`}
                language={active.language}
                readOnly={active.access === "read" || !active.loaded}
                replacementVersion={active.replacementVersion}
                value={active.content}
                onChange={model.change}
                onSave={model.save}
              />
            </Suspense>
          </div>
        ) : (
          <div className="studio-source-loading" role="status">
            {emptySource}
          </div>
        )}
      </div>
    </>
  );
};
