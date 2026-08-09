import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { notebookRouteQuery, publicNotebookQuery } from "@marimo-studio/protocol/query";
import { selectRuntimeInUrl } from "@marimo-studio/protocol/runtime-selection";
import { appendUrlPath } from "@marimo-studio/protocol/url";

export class StudioRoutes {
  private notebookQuery = publicNotebookQuery(globalThis.location.search);
  private readonly routeQuery = notebookRouteQuery(globalThis.location.search);

  constructor(private readonly bootstrap: StudioBootstrap) {}

  view = (view: string, runtime: string): string =>
    selectRuntimeInUrl(
      this.withNotebookQuery(
        appendUrlPath(
          this.bootstrap.urls.viewPrefix,
          `${encodeURIComponent(view)}/`,
          globalThis.location.href,
        ),
      ),
      runtime,
      this.bootstrap.defaultRuntime,
    );

  studio = (view: string): string =>
    this.withNotebookQuery(
      appendUrlPath(
        this.bootstrap.urls.studioPrefix,
        `${encodeURIComponent(view)}/`,
        globalThis.location.href,
      ),
    );

  support = (view: string): string =>
    appendUrlPath(
      this.bootstrap.urls.viewSupportPrefix,
      encodeURIComponent(view),
      globalThis.location.href,
    );

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

  private withNotebookQuery(url: string): string {
    const result = new URL(url, globalThis.location.href);
    result.search = this.pageQuery(this.notebookQuery);
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
