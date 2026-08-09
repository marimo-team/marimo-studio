import { publicNotebookQuery } from "@marimo-studio/protocol/query";

export interface ViewNavigation {
  view: string;
  current: boolean;
  documentUrl: string;
}

export const viewNavigationForUrl = ({
  href,
  origin,
  publicRootUrl,
  documentRootUrl,
  publicQuery,
  views,
  currentView,
}: {
  href: string;
  origin: string;
  publicRootUrl: string;
  documentRootUrl: string;
  publicQuery: string;
  views: readonly string[];
  currentView: string;
}): ViewNavigation | undefined => {
  const candidate = new URL(href);
  const publicRoot = new URL(publicRootUrl, origin);
  if (candidate.origin !== publicRoot.origin) {
    return undefined;
  }
  const documentRoot = new URL(documentRootUrl, origin);
  const view = views.find((name) => {
    const publicView = new URL(`${encodeURIComponent(name)}/`, publicRoot);
    const authoredView = new URL(`${encodeURIComponent(name)}/`, documentRoot);
    return [publicView, authoredView].some((viewUrl) => candidate.pathname === viewUrl.pathname);
  });
  if (!view) {
    return undefined;
  }
  const publicViewUrl = new URL(`${encodeURIComponent(view)}/`, publicRoot);
  publicViewUrl.search = publicRoot.search;
  const viewQuery = candidate.search ? publicNotebookQuery(candidate.search) : publicQuery;
  for (const [key, value] of new URLSearchParams(viewQuery)) {
    publicViewUrl.searchParams.append(key, value);
  }
  publicViewUrl.hash = candidate.hash;
  return {
    view,
    current: view === currentView,
    documentUrl: publicViewUrl.toString(),
  };
};
