import { fetchRuntimeConfigForRevision } from "./runtime-config/remote.ts";
import { commitRuntimeConfig, getMountConfig } from "./runtime-config/store.ts";

export * from "./runtime-config/remote.ts";
export * from "./runtime-config/schema.ts";
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
} from "./runtime-config/store.ts";

export const loadRuntimeConfig = async () => {
  const mount = getMountConfig();
  return commitRuntimeConfig(
    await fetchRuntimeConfigForRevision(
      mount.supportUrl,
      mount.revision,
    ),
  );
};
