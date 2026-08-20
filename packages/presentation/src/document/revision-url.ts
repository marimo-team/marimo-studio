import { PRESENTATION_REVISION_QUERY_PARAM } from "@marimo-studio/protocol/query";

export const unpinnedPresentationUrl = (source: string): string => {
  const url = new URL(source, globalThis.location.href);
  url.searchParams.delete(PRESENTATION_REVISION_QUERY_PARAM);
  return url.href;
};

export const releasePresentationRevisionPin = (): void => {
  const current = new URL(globalThis.location.href);
  if (!current.searchParams.has(PRESENTATION_REVISION_QUERY_PARAM)) {
    return;
  }
  globalThis.history.replaceState(
    globalThis.history.state,
    "",
    unpinnedPresentationUrl(current.href),
  );
};
