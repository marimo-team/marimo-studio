import type {
  PreparedProjectionCheckpoint,
  PreparedProjectionHandle,
} from "@marimo-studio/presentation/prepared-projections";
import type { PreparedStateChange, PreparedStatePort } from "@marimo-team/marimo-export/prepared";

import { notifyNotebookResults } from "@marimo-studio/presentation/render-inputs";

import type { StudioPreparedManifestSource } from "./metadata.ts";
import type { ZeroPythonProjectionLoaders } from "./projections.ts";

import { loadPreparedProjectionSnapshot } from "./projections.ts";

export class StudioPreparedRenderer implements PreparedStatePort {
  private shown?: PreparedStateChange["next"];

  constructor(
    private readonly renderer: PreparedProjectionHandle,
    private readonly source: StudioPreparedManifestSource,
    private readonly loaders: ZeroPythonProjectionLoaders,
    private readonly ownerCell: (selector: string) => string,
  ) {}

  async apply(change: PreparedStateChange, signal: AbortSignal): Promise<void> {
    const metadata = this.source.validate(change.next);
    const snapshot = await loadPreparedProjectionSnapshot(
      change.next.state,
      metadata.projections,
      this.loaders,
      this.ownerCell,
      signal,
    );
    signal.throwIfAborted();
    await this.renderer.replace(snapshot, { signal });
    this.renderer.updateControlBindings(change.next.notebookExport.controlBindings);
    this.source.remember(change.next.notebookExport);
    this.shown = change.next;
    notifyNotebookResults();
  }

  async restore(publication: PreparedStateChange["next"]): Promise<void> {
    await this.renderer.restore();
    this.renderer.updateControlBindings(publication.notebookExport.controlBindings);
    this.shown = publication;
    notifyNotebookResults();
  }

  /** The publication whose state the page's hosts show. */
  get publication(): PreparedStateChange["next"] | undefined {
    return this.shown;
  }

  checkpoint(): PreparedProjectionCheckpoint {
    return this.renderer.checkpoint();
  }

  update(presentation: Parameters<PreparedProjectionHandle["update"]>[0]): void {
    this.renderer.update(presentation);
  }

  dispose(): Promise<void> {
    return this.renderer.dispose();
  }
}
