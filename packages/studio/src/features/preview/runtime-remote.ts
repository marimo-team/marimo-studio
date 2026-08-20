import { parseRuntimeAvailability } from "@marimo-studio/protocol/runtime-descriptor";
import { appendUrlPath } from "@marimo-studio/protocol/url";

export interface LoadedRuntimeAvailability {
  readonly runtimes: readonly string[];
  readonly revision: string | null;
}

export type LoadRuntimeAvailability = (
  view: string,
  sources: Readonly<Record<"index.html" | "app.css", string>>,
  signal?: AbortSignal,
) => Promise<LoadedRuntimeAvailability>;

export const createRuntimeAvailabilityRemote =
  (supportUrl: (view: string) => string): LoadRuntimeAvailability =>
  async (view, sources, signal) => {
    const url = new URL(
      appendUrlPath(supportUrl(view), "runtimes", globalThis.location.href),
      globalThis.location.href,
    );
    url.searchParams.set("source_index", sources["index.html"]);
    url.searchParams.set("source_style", sources["app.css"]);
    const response = await fetch(url, { cache: "no-store", signal });
    if (!response.ok) {
      throw new Error(`Could not load runtimes for ${view} (${response.status})`);
    }
    const availability = parseRuntimeAvailability(await response.json());
    if (availability.view !== view) {
      throw new Error(
        `Runtime availability returned ${JSON.stringify(availability.view)} for ${JSON.stringify(view)}`,
      );
    }
    if (
      availability.sources["index.html"] !== sources["index.html"] ||
      availability.sources["app.css"] !== sources["app.css"]
    ) {
      throw new Error(`Runtime availability changed while loading ${JSON.stringify(view)}`);
    }
    return {
      runtimes: availability.runtimes,
      revision: availability.revision,
    };
  };
