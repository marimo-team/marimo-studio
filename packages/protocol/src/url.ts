/**
 * Resolve a URL reference against the URL of the response or document that
 * carried it. Studio records hold references relative to their carrier, and
 * parsers resolve them once so later code works with absolute URLs.
 */
export const resolveUrl = (reference: string, base: string | URL): string =>
  new URL(reference, base).href;

/** Append path segments to an absolute URL, keeping its query. */
export const appendUrlPath = (source: string, path: string): string => {
  const url = new URL(source);
  const prefix = url.pathname.endsWith("/") ? url.pathname : `${url.pathname}/`;
  url.pathname = `${prefix}${path.replace(/^\/+/, "")}`;
  return url.toString();
};
