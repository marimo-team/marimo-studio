import type { DocumentRevisionCommit } from "./revision-document.ts";

type ReplaceView = (
  documentUrl: string,
  supportUrl: string,
) => Promise<DocumentRevisionCommit | undefined>;

interface DevelopmentViewTransitionOptions {
  embedded: boolean;
  closeEvents: () => void;
  connectEvents: () => void;
  replaceView: ReplaceView;
}

export class DevelopmentViewTransition {
  private generation = 0;

  constructor(private readonly options: DevelopmentViewTransitionOptions) {}

  async run(documentUrl: string, supportUrl: string): Promise<void> {
    const generation = ++this.generation;
    if (!this.options.embedded) {
      this.options.closeEvents();
    }
    try {
      const commit = await this.options.replaceView(documentUrl, supportUrl);
      this.reconnect(generation, commit);
    } catch {
      this.reconnect(generation);
    }
  }

  cancel(): void {
    this.generation += 1;
  }

  private reconnect(generation: number, commit?: DocumentRevisionCommit): void {
    if (
      this.options.embedded ||
      generation !== this.generation ||
      commit?.supportChanged === true
    ) {
      return;
    }
    this.options.connectEvents();
  }
}
