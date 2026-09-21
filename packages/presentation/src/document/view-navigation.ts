import {
  publicNotebookQuery,
  EDITOR_SESSION_QUERY_PARAM,
  STUDIO_CLIENT_QUERY_PARAM,
  PRESENTATION_REVISION_QUERY_PARAM,
  UNFRAMED_QUERY_PARAM,
} from "@marimo-studio/protocol/query";

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

export const setEditorBindingQuery = (url: URL, clientId?: string, supportUrl?: string): void => {
  if (!clientId || !supportUrl) {
    return;
  }
  const session = new URL(supportUrl, url).searchParams.get(EDITOR_SESSION_QUERY_PARAM);
  if (session) {
    url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, clientId);
    url.searchParams.set(EDITOR_SESSION_QUERY_PARAM, session);
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
  exactRevision,
  clientId,
  supportUrl,
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
  exactRevision?: string | null;
  clientId?: string;
  supportUrl?: string;
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
  documentUrl.searchParams.delete(PRESENTATION_REVISION_QUERY_PARAM);
  if (directView === currentView && exactRevision) {
    documentUrl.searchParams.set(PRESENTATION_REVISION_QUERY_PARAM, exactRevision);
  }
  setTrustedRuntimeQuery(documentUrl, trustedRuntime);
  setEditorBindingQuery(documentUrl, clientId, supportUrl);
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
