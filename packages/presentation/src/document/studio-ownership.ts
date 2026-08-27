import type { MountConfig } from "@marimo-studio/protocol/runtime-config";

import { getMountConfig } from "../runtime-config/index.ts";

export const studioOwned = (
  identity: Pick<MountConfig, "clientId" | "lifecycleId"> = getMountConfig(),
): boolean => identity.clientId !== undefined && identity.lifecycleId !== undefined;
