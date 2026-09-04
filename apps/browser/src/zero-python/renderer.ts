import type {
  PreparedProjectionCheckpoint,
  PreparedProjectionHandle,
} from "@marimo-studio/presentation/prepared-projections";
import type { PreparedStateChange, PreparedStatePort } from "@marimo-team/marimo-export/prepared";

import type { StudioPreparedManifestSource } from "./metadata.ts";
import type { ZeroPythonProjectionLoaders } from "./projections.ts";

import { loadPreparedProjectionSnapshot } from "./projections.ts";

export class StudioPreparedRenderer implements PreparedStatePort {
  constructor(
    private readonly renderer: PreparedProjectionHandle,
    private readonly source: StudioPreparedManifestSource,
    private readonly loaders: ZeroPythonProjectionLoaders,
  ) {}

  async apply(change: PreparedStateChange, signal: AbortSignal): Promise<void> {
    const metadata = this.source.validate(change.next);
    const snapshot = await loadPreparedProjectionSnapshot(
      change.next.state,
      metadata.projections,
      this.loaders,
      signal,
    );
    signal.throwIfAborted();
    await this.renderer.replace(snapshot, { signal });
    this.renderer.updateControlBindings(change.next.notebookExport.controlBindings);
    this.source.remember(change.next.notebookExport);
  }

  async restore(publication: PreparedStateChange["next"]): Promise<void> {
    await this.renderer.restore();
    this.renderer.updateControlBindings(publication.notebookExport.controlBindings);
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
