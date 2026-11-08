import { getMountConfig } from "../runtime-config/index.ts";

const MAX_LIFECYCLE_ID = Number.MAX_SAFE_INTEGER - 1;
let current: number | undefined;

export const setActiveDocumentLifecycleId = (lifecycleId: number): void => {
  current = lifecycleId;
};

export const activeDocumentLifecycleId = (): number => {
  // Studio assigns the lifecycle of a document it owns. A standalone document
  // mints its own, so the wrapper can tell it apart from the document it replaced.
  current ??= getMountConfig().lifecycleId ?? 1 + Math.floor(Math.random() * MAX_LIFECYCLE_ID);
  return current;
};

export const documentLifecycleEnvelope = () => ({
  lifecycleId: activeDocumentLifecycleId(),
});
