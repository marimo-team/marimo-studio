import { parseSourceChanges, type SourceFileChange } from "@marimo-studio/protocol/source-events";

export class SourceEvents {
  private events: EventSource | undefined;

  open(url: string, onReady: () => void, onChange: (change: SourceFileChange) => void): void {
    this.close();
    this.events = new EventSource(url);
    this.events.addEventListener("ready", onReady);
    this.events.addEventListener("change", (event) => {
      const data = event instanceof MessageEvent ? String(event.data) : "";
      for (const change of parseSourceChanges(data)) {
        onChange(change);
      }
    });
  }

  close(): void {
    this.events?.close();
    this.events = undefined;
  }
}
