import type { ActiveViewRequest } from "@marimo-studio/protocol/development-events";
import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import type { ControlFrameConnector } from "../features/preview/control-sync.ts";
import type { StudioBrand, ThemeFrameConnector } from "../shared/theme.tsx";

import { Toolbar } from "../features/navigation/Toolbar.tsx";
import { useWorkspace } from "../features/workspace/useWorkspace.ts";
import { Workspace } from "../features/workspace/Workspace.tsx";
import { StudioThemeProvider, useResolvedStudioTheme } from "../shared/theme.tsx";
import { StudioErrorBoundary } from "./StudioErrorBoundary.tsx";
import { useStudioServices } from "./useStudioServices.ts";

export interface StudioOptions {
  brand: StudioBrand;
  connectControlFrame?: ControlFrameConnector;
  connectThemeFrame?: ThemeFrameConnector;
}

interface StudioAppProps extends StudioOptions {
  bootstrap: StudioBootstrap;
  editorFrame: HTMLIFrameElement;
  initialActivation?: ActiveViewRequest;
  onRetry: () => void;
}

const StudioWorkspace = ({
  bootstrap,
  brand,
  connectControlFrame,
  connectThemeFrame,
  editorFrame,
  initialActivation,
}: StudioAppProps) => {
  const services = useStudioServices(
    bootstrap,
    editorFrame,
    initialActivation,
    connectControlFrame,
  );
  const workspace = useWorkspace(services.layout, services.preview, services.views);
  const theme = useResolvedStudioTheme(services.editorFrame, connectThemeFrame);

  return (
    <StudioThemeProvider theme={theme}>
      <div className="studio" data-mode={workspace.layout.mode} data-theme={theme}>
        <Toolbar
          bootstrap={bootstrap}
          brand={brand}
          compact={workspace.geometry.compact}
          compactSurfaces={workspace.geometry.surfaces}
          layout={services.layout}
          preview={services.preview}
          views={services.views}
        />
        <Workspace
          bootstrap={bootstrap}
          editorFrame={editorFrame}
          frameRef={services.frameRef}
          source={services.source}
          workspace={workspace}
        />
      </div>
    </StudioThemeProvider>
  );
};

export const StudioApp = (props: StudioAppProps) => (
  <StudioErrorBoundary editorUrl={props.bootstrap.urls.editor} onRetry={props.onRetry}>
    <StudioWorkspace {...props} />
  </StudioErrorBoundary>
);
