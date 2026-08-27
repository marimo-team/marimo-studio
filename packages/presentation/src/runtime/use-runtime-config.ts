import { useSyncExternalStore } from "react";

import {
  getRuntimeConfig,
  getRuntimeProjectionConfig,
  subscribeRuntimeConfig,
  subscribeRuntimeProjectionConfig,
} from "../runtime-config/index";

export const useRuntimeConfig = () =>
  useSyncExternalStore(subscribeRuntimeConfig, getRuntimeConfig, getRuntimeConfig);

export const useRuntimeProjectionConfig = () =>
  useSyncExternalStore(
    subscribeRuntimeProjectionConfig,
    getRuntimeProjectionConfig,
    getRuntimeProjectionConfig,
  );
