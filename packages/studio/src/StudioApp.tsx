import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import type { ControlFrameConnector } from "./preview/control-sync.ts";
import type { StudioBrand, ThemeFrameConnector } from "./theme.tsx";

import { StudioErrorBoundary } from "./app/StudioErrorBoundary.tsx";
import { useStudioServices } from "./app/useStudioServices.ts";
import { Toolbar } from "./components/toolbar/Toolbar.tsx";
import { useWorkspace } from "./layout/useWorkspace.ts";
import { Workspace } from "./layout/Workspace.tsx";
import { StudioThemeProvider, useResolvedStudioTheme } from "./theme.tsx";

export interface StudioOptions {
  brand: StudioBrand;
  connectControlFrame?: ControlFrameConnector;
  connectThemeFrame?: ThemeFrameConnector;
}

interface StudioAppProps extends StudioOptions {
  bootstrap: StudioBootstrap;
}

const StudioWorkspace = ({
  bootstrap,
  brand,
  connectControlFrame,
  connectThemeFrame,
}: StudioAppProps) => {
  const services = useStudioServices(bootstrap, connectControlFrame);
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
          editorRef={services.editorRef}
          frameRef={services.frameRef}
          source={services.source}
          workspace={workspace}
        />
      </div>
    </StudioThemeProvider>
  );
};

export const StudioApp = (props: StudioAppProps) => (
  <StudioErrorBoundary editorUrl={props.bootstrap.urls.editor}>
    <StudioWorkspace {...props} />
  </StudioErrorBoundary>
);
