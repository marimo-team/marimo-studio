export interface ViewNavigation {
  view: string;
  current: boolean;
}

export const viewNavigationForUrl = ({
  href,
  origin,
  rootUrl,
  views,
  currentView,
}: {
  href: string;
  origin: string;
  rootUrl: string;
  views: readonly string[];
  currentView: string;
}): ViewNavigation | undefined => {
  const candidate = new URL(href);
  const runtimeRoot = new URL(rootUrl, origin);
  if (candidate.origin !== runtimeRoot.origin || candidate.search || candidate.hash) {
    return undefined;
  }
  const view = views.find((name) => {
    const viewUrl = new URL(`${encodeURIComponent(name)}/`, runtimeRoot);
    return candidate.pathname === viewUrl.pathname;
  });
  return view ? { view, current: view === currentView } : undefined;
};
