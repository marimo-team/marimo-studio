/**
 * Navigate this document to `hash` without loading another document.
 *
 * The browser treats the change as a fragment navigation: it fires `popstate`
 * and, when the fragment changes, `hashchange`, then scrolls to the element
 * the fragment names. Hash routers and plain anchors therefore observe Studio's
 * fragment changes the same way they observe their own. `replace` keeps the
 * session history length, and `push` adds one entry. As with any fragment
 * navigation, the new entry starts with `history.state` set to null.
 */
export const navigateToFragment = (hash: string, history: "push" | "replace" = "replace"): void => {
  const target = new URL(globalThis.location.href);
  target.hash = hash;
  // A URL without "#" names another document. An empty fragment keeps the
  // navigation inside this one.
  const href = target.hash ? target.href : `${target.href}#`;
  if (history === "push") {
    globalThis.location.assign(href);
  } else {
    globalThis.location.replace(href);
  }
};

/** Return `url` with the fragment of the current document location. */
export const withCurrentFragment = (url: string): string => {
  const target = new URL(url, globalThis.location.href);
  target.hash = globalThis.location.hash;
  return target.href;
};
