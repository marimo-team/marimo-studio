import { getMountConfig } from "../runtime-config/index.ts";

let current: number | undefined;

export const setActiveDocumentLifecycleId = (lifecycleId: number): void => {
  current = lifecycleId;
};

export const activeDocumentLifecycleId = (): number => {
  current ??= getMountConfig().lifecycleId;
  return current ?? 1;
};

export const documentLifecycleEnvelope = () => ({
  lifecycleId: activeDocumentLifecycleId(),
});
