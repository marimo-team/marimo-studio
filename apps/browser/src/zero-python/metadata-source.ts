import type { NotebookExport } from "@marimo-team/marimo-export";
import type {
  PreparedExportManifest,
  PreparedManifestFetchOptions,
  PreparedPublication,
} from "@marimo-team/marimo-export/prepared";

import { fetchPreparedManifestDocument } from "@marimo-team/marimo-export/prepared";
import { z } from "zod";

import type { StudioPreparedContext, StudioPreparedManifest } from "./metadata-records.ts";

import { parseStudioPreparedManifest } from "./metadata-records.ts";
import { validateStudioPreparedManifest } from "./metadata-validation.ts";

/** The presentation revision moved on while this manifest URL was in use. */
export class StalePreparedBindingError extends Error {
  constructor() {
    super("The presentation is refreshing its notebook bindings.");
    this.name = "StalePreparedBindingError";
  }
}

const staleBindingSchema = z.object({ error: z.literal("stale-projection-binding") });

const isStaleBinding = async (response: Response): Promise<boolean> =>
  response.status === 409 &&
  staleBindingSchema.safeParse(
    await response
      .clone()
      .json()
      .catch(() => null),
  ).success;

const bindingAwareFetch =
  (fetcher: typeof globalThis.fetch): typeof globalThis.fetch =>
  async (input, init) => {
    const response = await fetcher(input, init);
    if (await isStaleBinding(response)) {
      await response.body?.cancel();
      throw new StalePreparedBindingError();
    }
    return response;
  };

export class StudioPreparedManifestSource {
  readonly #metadata = new WeakMap<PreparedExportManifest, StudioPreparedManifest>();
  readonly #exports = new Map<string, NotebookExport>();

  constructor(
    private readonly context: () => StudioPreparedContext,
    private readonly fetcher: typeof globalThis.fetch = globalThis.fetch,
  ) {}

  async fetch(
    url: URL,
    options: PreparedManifestFetchOptions = {},
    expectedInstance?: string,
  ): Promise<PreparedExportManifest> {
    const metadata = parseStudioPreparedManifest(
      await fetchPreparedManifestDocument(url, {
        ...options,
        fetch: bindingAwareFetch(options.fetch ?? this.fetcher),
      }),
    );
    validateStudioPreparedManifest(
      metadata,
      this.context(),
      this.#exports.get(metadata.prepared.instance),
      expectedInstance,
    );
    this.#metadata.set(metadata.prepared, metadata);
    return metadata.prepared;
  }

  metadata(manifest: PreparedExportManifest): StudioPreparedManifest {
    const metadata = this.#metadata.get(manifest);
    if (metadata === undefined) {
      throw new Error("The prepared export has no Studio view metadata.");
    }
    return metadata;
  }

  validate(publication: PreparedPublication): StudioPreparedManifest {
    const metadata = this.metadata(publication.manifest);
    validateStudioPreparedManifest(metadata, this.context(), publication.notebookExport);
    return metadata;
  }

  remember(notebookExport: NotebookExport): void {
    this.#exports.delete(notebookExport.identity);
    this.#exports.set(notebookExport.identity, notebookExport);
    while (this.#exports.size > 2) {
      const oldest = this.#exports.keys().next().value;
      if (oldest === undefined) {
        return;
      }
      this.#exports.delete(oldest);
    }
  }
}
