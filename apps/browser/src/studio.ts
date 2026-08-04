import { connectMarimoControlFrame } from "@marimo-studio/marimo-frontend/control-frame";
import { connectMarimoThemeFrame } from "@marimo-studio/marimo-frontend/theme-frame";
import { startStudio } from "@marimo-studio/studio";

import darkMark from "../../docs/public/brand/marimo-studio-mark-dark.svg?url";
import lightMark from "../../docs/public/brand/marimo-studio-mark-light.svg?url";

await startStudio({
  brand: { marks: { dark: darkMark, light: lightMark } },
  connectControlFrame: connectMarimoControlFrame,
  connectThemeFrame: connectMarimoThemeFrame,
});
