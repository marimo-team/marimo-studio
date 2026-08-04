import { connectMarimoControlFrame } from "@marimo-studio/marimo-frontend/control-frame";
import { startStudio } from "@marimo-studio/studio";

await startStudio({ connectControlFrame: connectMarimoControlFrame });
