import type { ViewNavigationIntent } from "@marimo-studio/protocol/preview-messages";
import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import {
  notebookRouteQuery,
  publicNotebookQuery,
  SERVER_INSTANCE_QUERY_PARAM,
  STUDIO_CLIENT_QUERY_PARAM,
} from "@marimo-studio/protocol/query";
import { selectRuntimeInUrl } from "@marimo-studio/protocol/runtime-selection";
import { appendUrlPath } from "@marimo-studio/protocol/url";

export class StudioRoutes {
  private notebookQuery = publicNotebookQuery(globalThis.location.search);
  private readonly routeQuery = notebookRouteQuery(globalThis.location.search);

  constructor(private readonly bootstrap: StudioBootstrap) {}

  view = (view: string, runtime: string, navigation?: ViewNavigationIntent): string => {
    const query = navigation?.query ?? this.notebookQuery;
    const selected = selectRuntimeInUrl(
      this.withNotebookQuery(
        appendUrlPath(
          this.bootstrap.urls.viewPrefix,
          `${encodeURIComponent(view)}/`,
          globalThis.location.href,
        ),
        query,
      ),
      runtime,
      this.bootstrap.defaultRuntime,
    );
    const url = new URL(selected, globalThis.location.href);
    url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, this.bootstrap.clientId);
    url.searchParams.set(SERVER_INSTANCE_QUERY_PARAM, this.bootstrap.serverInstance);
    url.hash = navigation?.hash ?? "";
    return url.toString();
  };

  currentNavigation = (): ViewNavigationIntent => ({
    query: this.notebookQuery,
    hash: globalThis.location.hash,
  });

  studio = (view: string): string =>
    this.withNotebookQuery(
      appendUrlPath(
        this.bootstrap.urls.studioPrefix,
        `${encodeURIComponent(view)}/`,
        globalThis.location.href,
      ),
    );

  support = (view: string): string => {
    const url = new URL(
      appendUrlPath(
        this.bootstrap.urls.viewSupportPrefix,
        encodeURIComponent(view),
        globalThis.location.href,
      ),
    );
    url.searchParams.set(SERVER_INSTANCE_QUERY_PARAM, this.bootstrap.serverInstance);
    return url.toString();
  };

  endpoint = (url: string): string => new URL(url, globalThis.location.href).toString();

  syncQuery = (query: string): void => {
    const next = publicNotebookQuery(query);
    if (next === this.notebookQuery) {
      return;
    }
    this.notebookQuery = next;
    const url = new URL(globalThis.location.href);
    url.search = this.pageQuery(next);
    globalThis.history.replaceState(
      globalThis.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  };

  private withNotebookQuery(url: string, query = this.notebookQuery): string {
    const result = new URL(url, globalThis.location.href);
    result.search = this.pageQuery(query);
    return result.toString();
  }

  private pageQuery(publicQuery: string): string {
    const parameters = new URLSearchParams(this.routeQuery);
    for (const [key, value] of new URLSearchParams(publicQuery)) {
      parameters.append(key, value);
    }
    return parameters.toString();
  }
}
