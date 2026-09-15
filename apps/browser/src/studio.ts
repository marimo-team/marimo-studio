import { connectControlEndpoint } from "@marimo-studio/marimo-frontend/control-endpoint";
import { connectMarimoEditorWorkspace } from "@marimo-studio/marimo-frontend/editor-workspace";
import { connectMarimoThemeFrame } from "@marimo-studio/marimo-frontend/theme-frame";
import { startStudio } from "@marimo-studio/studio";
import {
  initializeStudioHostSession,
  readHostSessionConfig,
} from "@marimo-studio/studio/host-session";

import darkMark from "../../docs/public/brand/marimo-studio-mark-dark.svg?url";
import lightMark from "../../docs/public/brand/marimo-studio-mark-light.svg?url";

initializeStudioHostSession(readHostSessionConfig());
startStudio({
  brand: { marks: { dark: darkMark, light: lightMark } },
  connectEditorWorkspace: connectMarimoEditorWorkspace,
  connectControlFrame: connectControlEndpoint,
  connectThemeFrame: connectMarimoThemeFrame,
});
