import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";
import type { RefCallback } from "react";

import type { SourceController } from "../source/controller.ts";
import type { WorkspaceState } from "./useWorkspace.ts";

import { SourcePane } from "../source/SourcePane.tsx";
import { Divider } from "./Divider.tsx";
import { SurfacePane } from "./SurfacePane.tsx";
import { PreviewFrame, TrustedFrame } from "./TrustedFrame.tsx";

interface WorkspaceProps {
  bootstrap: StudioBootstrap;
  editorRef: RefCallback<HTMLIFrameElement>;
  frameRef: (runtime: string) => RefCallback<HTMLIFrameElement>;
  source: SourceController;
  workspace: WorkspaceState;
}

export const Workspace = ({
  bootstrap,
  editorRef,
  frameRef,
  source,
  workspace,
}: WorkspaceProps) => {
  const { actions, currentView, geometry, preview, ref, resizing } = workspace;
  const layoutSnapshot = workspace.layout;
  const notebookRectangle = geometry.layout.panes.get("notebook");
  const sourceRectangle = geometry.layout.panes.get("source");
  const previewRectangle = geometry.layout.panes.get("preview");

  return (
    <main
      ref={ref}
      className="studio-workspace"
      aria-label="Studio workspace"
      data-compact={geometry.compact}
      data-arranging={layoutSnapshot.arranging}
      data-resizing={resizing ?? undefined}
    >
      <div className="studio-surface-layer">
        <SurfacePane
          label="Notebook"
          surface="notebook"
          rectangle={notebookRectangle}
          tree={layoutSnapshot.tree}
          arranging={layoutSnapshot.arranging}
          onArrange={actions.arrangePane}
        >
          <div className="studio-pane-content">
            <TrustedFrame frameRef={editorRef} src={bootstrap.urls.editor} title="Marimo editor" />
          </div>
        </SurfacePane>

        <SurfacePane
          label="HTML & CSS"
          surface="source"
          rectangle={sourceRectangle}
          tree={layoutSnapshot.tree}
          arranging={layoutSnapshot.arranging}
          onArrange={actions.arrangePane}
        >
          <SourcePane controller={source} visible={sourceRectangle !== undefined} />
        </SurfacePane>

        <SurfacePane
          label="Preview"
          surface="preview"
          rectangle={previewRectangle}
          tree={layoutSnapshot.tree}
          arranging={layoutSnapshot.arranging}
          onArrange={actions.arrangePane}
        >
          <div className="studio-pane-content">
            {bootstrap.runtimes.map((runtime) => {
              const active = preview.runtime === runtime.id;
              return (
                <PreviewFrame
                  key={runtime.id}
                  runtime={runtime.id}
                  frameRef={frameRef(runtime.id)}
                  src="about:blank"
                  title={`${currentView} custom view using ${runtime.id}`}
                  active={active}
                />
              );
            })}
          </div>
        </SurfacePane>
      </div>

      <div className="studio-divider-layer">
        {geometry.layout.dividers.map((divider) => (
          <Divider
            key={divider.id}
            divider={divider}
            tree={layoutSnapshot.tree}
            workspace={workspace.element}
            onPreview={actions.previewResize}
            onCommit={actions.commitResize}
            onCancel={actions.cancelResize}
            onResize={actions.setResizing}
          />
        ))}
      </div>
      <div
        className="studio-resize-scrim"
        data-axis={resizing ?? undefined}
        hidden={resizing === null}
      />
    </main>
  );
};
