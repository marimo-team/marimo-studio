import { publicNotebookQuery, UNFRAMED_QUERY_PARAM } from "@marimo-studio/protocol/query";

export interface ViewNavigation {
  view: string;
  current: boolean;
  documentUrl: string;
}

export interface ViewHistoryNavigation {
  navigation: ViewNavigation;
  publicQueryChanged: boolean;
}

export interface TrustedRuntimeSelection {
  id: string;
  explicit: boolean;
}

export const setTrustedRuntimeQuery = (url: URL, selection: TrustedRuntimeSelection): void => {
  url.searchParams.delete("runtime");
  if (selection.explicit) {
    url.searchParams.set("runtime", selection.id);
  }
};

const publicViewUrl = (root: URL, view: string, query: string): URL => {
  const url = new URL(`${encodeURIComponent(view)}/`, root);
  url.search = root.search;
  for (const [key, value] of new URLSearchParams(query)) {
    url.searchParams.append(key, value);
  }
  return url;
};

export const viewNavigationForUrl = ({
  href,
  origin,
  publicRootUrl,
  documentRootUrl,
  publicQuery,
  trustedRuntime,
  unframed,
  views,
  currentView,
}: {
  href: string;
  origin: string;
  publicRootUrl: string;
  documentRootUrl: string;
  publicQuery: string;
  trustedRuntime: TrustedRuntimeSelection;
  unframed: boolean;
  views: readonly string[];
  currentView: string;
}): ViewNavigation | undefined => {
  const publicRoot = new URL(publicRootUrl, origin);
  const candidate = new URL(href, publicViewUrl(publicRoot, currentView, publicQuery));
  if (candidate.origin !== publicRoot.origin) {
    return undefined;
  }
  const documentRoot = new URL(documentRootUrl, origin);
  const directView = views.find((name) => {
    const publicView = new URL(`${encodeURIComponent(name)}/`, publicRoot);
    const authoredView = new URL(`${encodeURIComponent(name)}/`, documentRoot);
    return [publicView, authoredView].some(
      (viewUrl) =>
        candidate.pathname === viewUrl.pathname ||
        candidate.pathname === `${viewUrl.pathname}index.html`,
    );
  });
  if (!directView) {
    return undefined;
  }
  const viewQuery = candidate.search ? publicNotebookQuery(candidate.search) : publicQuery;
  const documentUrl = publicViewUrl(publicRoot, directView, viewQuery);
  setTrustedRuntimeQuery(documentUrl, trustedRuntime);
  if (unframed) {
    documentUrl.searchParams.set(UNFRAMED_QUERY_PARAM, "1");
  }
  documentUrl.hash = candidate.hash;
  return {
    view: directView,
    current: directView === currentView,
    documentUrl: documentUrl.toString(),
  };
};

export const viewHistoryNavigationForUrl = ({
  mountedDocumentUrl,
  ...navigationOptions
}: Parameters<typeof viewNavigationForUrl>[0] & {
  mountedDocumentUrl: string;
}): ViewHistoryNavigation | undefined => {
  const navigation = viewNavigationForUrl(navigationOptions);
  if (!navigation) {
    return undefined;
  }
  const mountedQuery = publicNotebookQuery(
    new URL(mountedDocumentUrl, navigationOptions.origin).search,
  );
  const requestedQuery = publicNotebookQuery(new URL(navigation.documentUrl).search);
  return {
    navigation,
    publicQueryChanged: requestedQuery !== mountedQuery,
  };
};
