import { fetchRuntimeConfigForRevision } from "./remote.ts";
import { commitRuntimeConfig, getMountConfig } from "./store.ts";

export * from "./remote.ts";
export * from "@marimo-studio/protocol/runtime-config";
export {
  commitRuntimeConfig,
  getMountConfig,
  getRuntimeCellRefs,
  getRuntimeConfig,
  getRuntimeDiagnostics,
  getRuntimeProjectionConfig,
  getSupportUrl,
  hasRuntimeConfig,
  setSupportUrl,
  subscribeRuntimeCellRefs,
  subscribeRuntimeConfig,
  subscribeRuntimeProjectionConfig,
} from "./store.ts";

export const loadRuntimeConfig = async (runtimeSessionId?: string, signal?: AbortSignal) => {
  const mount = getMountConfig();
  return commitRuntimeConfig(
    await fetchRuntimeConfigForRevision(
      mount.supportUrl,
      mount.revision,
      signal,
      mount.runtime,
      mount.sessionId,
      runtimeSessionId,
    ),
  );
};
