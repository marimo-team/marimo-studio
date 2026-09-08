import type { RuntimeProgress } from "@marimo-studio/protocol/runtime-progress";

interface RuntimeProgressUpdate {
  runtime: string;
  supportUrl: string;
  revision: string;
  progress: RuntimeProgress | null;
  configured?: true;
}
type Listener = (update: RuntimeProgressUpdate) => void;

export class RuntimeProgressStore {
  private owner: object | undefined;
  private readonly listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  begin(runtime: string, supportUrl: string, revision: string) {
    const owner = {};
    this.owner = owner;
    const publish = (progress: RuntimeProgress | null, configured = false) => {
      if (this.owner !== owner) return;
      const update: RuntimeProgressUpdate = { runtime, supportUrl, revision, progress };
      if (configured) update.configured = true;
      for (const listener of this.listeners) listener(update);
    };
    return {
      report: publish,
      close: (configured = false) => {
        if (this.owner !== owner) return;
        publish(null, configured);
        if (this.owner === owner) this.owner = undefined;
      },
    };
  }
}

export const runtimeProgress = new RuntimeProgressStore();
