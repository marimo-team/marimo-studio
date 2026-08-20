import { startPresentation } from "@marimo-studio/presentation/runtime";
import { createRuntimeRegistry } from "@marimo-studio/runtime";

import { zeroPythonRuntime } from "./zero-python/runtime.ts";

startPresentation(createRuntimeRegistry([zeroPythonRuntime]));
