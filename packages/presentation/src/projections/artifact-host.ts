const NATIVE_OUTPUT_SELECTOR = "[data-marimo-cell-output]";

const composedParent = (element: Element): Element | null => {
  if (element.parentElement !== null) {
    return element.parentElement;
  }
  const root = element.getRootNode();
  return root instanceof ShadowRoot ? root.host : null;
};

export const isArtifactProjectionHost = (element: Element): boolean => {
  let current: Element | null = element;
  while (current !== null) {
    if (current.matches(NATIVE_OUTPUT_SELECTOR)) {
      return false;
    }
    current = composedParent(current);
  }
  return true;
};
