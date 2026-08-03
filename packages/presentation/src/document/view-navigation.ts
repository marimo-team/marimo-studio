export interface ViewNavigation {
  view: string;
  current: boolean;
}

export const viewNavigationForUrl = ({
  href,
  origin,
  runtimeUrl,
  views,
  currentView,
}: {
  href: string;
  origin: string;
  runtimeUrl: string;
  views: readonly string[];
  currentView: string;
}): ViewNavigation | undefined => {
  const candidate = new URL(href);
  const runtimeRoot = new URL(runtimeUrl, origin);
  if (candidate.origin !== runtimeRoot.origin || candidate.search || candidate.hash) {
    return undefined;
  }
  const view = views.find((name) => {
    const viewUrl = new URL(`${encodeURIComponent(name)}/`, runtimeRoot);
    return candidate.pathname === viewUrl.pathname;
  });
  return view ? { view, current: view === currentView } : undefined;
};
