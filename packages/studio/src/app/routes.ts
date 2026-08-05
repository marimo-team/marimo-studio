import type { StudioBootstrap } from "@marimo-studio/protocol/studio-bootstrap";

import { publicNotebookQuery } from "@marimo-studio/protocol/query";
import { selectRuntimeInUrl } from "@marimo-studio/protocol/runtime-selection";

export class StudioRoutes {
  private notebookQuery = publicNotebookQuery(globalThis.location.search);

  constructor(private readonly bootstrap: StudioBootstrap) {}

  view = (view: string, runtime: string): string =>
    selectRuntimeInUrl(
      new URL(
        `${this.bootstrap.urls.viewPrefix}${view}/${this.notebookQuery}`,
        globalThis.location.href,
      ).toString(),
      runtime,
      this.bootstrap.defaultRuntime,
    );

  studio = (view: string): string =>
    `${this.bootstrap.urls.studioPrefix}${view}/${this.notebookQuery}`;

  support = (view: string): string =>
    `${this.bootstrap.urls.viewSupportPrefix}/${encodeURIComponent(view)}`;

  syncQuery = (query: string): void => {
    const next = publicNotebookQuery(query);
    if (next === this.notebookQuery) {
      return;
    }
    this.notebookQuery = next;
    const url = new URL(globalThis.location.href);
    url.search = next;
    globalThis.history.replaceState(
      globalThis.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  };
}
