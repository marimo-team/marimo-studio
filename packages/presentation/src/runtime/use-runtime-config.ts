import { useSyncExternalStore } from "react";

import {
  getRuntimeProjectionConfig,
  subscribeRuntimeProjectionConfig,
} from "../runtime-config/index";

export const useRuntimeProjectionConfig = () =>
  useSyncExternalStore(
    subscribeRuntimeProjectionConfig,
    getRuntimeProjectionConfig,
    getRuntimeProjectionConfig,
  );
