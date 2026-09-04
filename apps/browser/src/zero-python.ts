import { startStaticPresentation } from "@marimo-studio/presentation/static-runtime";
import { createRuntimeRegistry } from "@marimo-studio/runtime";

import { zeroPythonRuntime } from "./zero-python/runtime.ts";

startStaticPresentation(createRuntimeRegistry([zeroPythonRuntime]));
