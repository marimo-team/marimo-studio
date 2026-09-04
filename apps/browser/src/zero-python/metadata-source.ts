import type { NotebookExport } from "@marimo-team/marimo-export";
import type {
  PreparedExportManifest,
  PreparedManifestFetchOptions,
  PreparedPublication,
} from "@marimo-team/marimo-export/prepared";

import type { StudioPreparedContext, StudioPreparedManifest } from "./metadata-records.ts";

import { fetchStudioPreparedManifest } from "./metadata-fetch.ts";
import { validateStudioPreparedManifest } from "./metadata-validation.ts";

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
    const metadata = await fetchStudioPreparedManifest(
      url,
      options.fetch ?? this.fetcher,
      options.signal,
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
