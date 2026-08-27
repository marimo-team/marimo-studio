import * as React from "react";

type PossibleRef<T> = React.Ref<T> | undefined;
type RefCleanup = () => void;

interface RefCacheNode {
  callback?: React.RefCallback<unknown>;
  objects: WeakMap<object, RefCacheNode>;
  optional: Map<null | undefined, RefCacheNode>;
}

const cacheNode = (): RefCacheNode => ({
  objects: new WeakMap(),
  optional: new Map(),
});

const composedRefCache = cacheNode();

const childCache = <T>(node: RefCacheNode, ref: PossibleRef<T>): RefCacheNode => {
  if (ref === null || ref === undefined) {
    let child = node.optional.get(ref);
    if (!child) {
      child = cacheNode();
      node.optional.set(ref, child);
    }
    return child;
  }
  let child = node.objects.get(ref);
  if (!child) {
    child = cacheNode();
    node.objects.set(ref, child);
  }
  return child;
};

const isRefCallback = <T>(ref: PossibleRef<T>): ref is React.RefCallback<T> =>
  ref instanceof Function;

const isRefCleanup = (cleanup: void | RefCleanup): cleanup is RefCleanup =>
  cleanup instanceof Function;

const setRef = <T>(ref: PossibleRef<T>, value: T): (() => void) | void => {
  if (isRefCallback(ref)) {
    return ref(value);
  }
  if (ref !== null && ref !== undefined) {
    ref.current = value;
  }
};

export const composeRefs = <T>(...refs: PossibleRef<T>[]): React.RefCallback<T> => {
  let cache = composedRefCache;
  refs.forEach((ref) => {
    cache = childCache(cache, ref);
  });
  cache.callback ??= (node) => {
    // SAFETY: This callback is reached through the cache path for this exact
    // ref tuple, whose composeRefs call established T.
    const attachedNode = node as T;
    const cleanups = refs.map((ref) => setRef(ref, attachedNode));
    return () => {
      cleanups.forEach((cleanup, index) => {
        if (isRefCleanup(cleanup)) {
          cleanup();
        } else {
          setRef(refs[index], null);
        }
      });
    };
  };
  // SAFETY: The cache path is keyed by the exact ref tuple accepted for T, so
  // its callback can be exposed through the same typed composeRefs call.
  return cache.callback as React.RefCallback<T>;
};

export const useComposedRefs = <T>(...refs: PossibleRef<T>[]): React.RefCallback<T> => {
  const current = React.useRef(refs);
  current.current = refs;
  // This presentation-scoped adapter for radix-ui/primitives#3963 keeps the
  // owner stable under React 19. Changed ref inputs apply on the next node
  // attachment, which prevents null-to-node update loops in projected output.
  return React.useCallback((node) => composeRefs(...current.current)(node), []);
};
