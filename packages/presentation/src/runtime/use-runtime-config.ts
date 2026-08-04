import { useSyncExternalStore } from "react";

import { getRuntimeConfig, subscribeRuntimeConfig } from "../runtime-config/index";

export const useRuntimeConfig = () =>
  useSyncExternalStore(subscribeRuntimeConfig, getRuntimeConfig, getRuntimeConfig);
