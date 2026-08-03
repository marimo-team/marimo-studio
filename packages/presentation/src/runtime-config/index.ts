import { fetchRuntimeConfigForRevision } from "./remote.ts";
import { commitRuntimeConfig, getMountConfig } from "./store.ts";

export * from "./remote.ts";
export * from "@marimo-studio/protocol/runtime-config";
export {
  commitRuntimeConfig,
  getRuntimeCellBindings,
  getRuntimeConfig,
  getRuntimeDiagnostics,
  getSupportUrl,
  hasRuntimeConfig,
  setSupportUrl,
  subscribeRuntimeCellBindings,
  subscribeRuntimeConfig,
} from "./store.ts";

export const loadRuntimeConfig = async () => {
  const mount = getMountConfig();
  return commitRuntimeConfig(await fetchRuntimeConfigForRevision(mount.supportUrl, mount.revision));
};
