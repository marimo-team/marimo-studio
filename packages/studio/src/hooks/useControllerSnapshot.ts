import { useCallback, useSyncExternalStore } from "react";

interface ExternalStore<T> {
  getSnapshot(): T;
  subscribe(listener: () => void): () => void;
}

export const useControllerSnapshot = <T>(store: ExternalStore<T>): T => {
  const subscribe = useCallback((listener: () => void) => store.subscribe(listener), [store]);
  const getSnapshot = useCallback(() => store.getSnapshot(), [store]);
  return useSyncExternalStore(subscribe, getSnapshot);
};
