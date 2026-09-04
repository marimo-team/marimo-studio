import { startPresentation } from "@marimo-studio/presentation/runtime";
import { serverRuntime, wasmRuntime } from "@marimo-studio/presentation/runtimes";
import { createRuntimeRegistry } from "@marimo-studio/runtime";

import { zeroPythonRuntime } from "./zero-python/runtime.ts";

startPresentation(createRuntimeRegistry([serverRuntime, wasmRuntime, zeroPythonRuntime]));
