import type { SourceName } from "./source-remote.ts";

export interface SourceFileChange {
  path: SourceName;
  revision: string | null;
}

export class SourceEvents {
  private events: EventSource | undefined;

  open(
    url: string,
    onReady: () => void,
    onChange: (change: SourceFileChange) => void,
  ): void {
    this.close();
    this.events = new EventSource(url);
    this.events.addEventListener("ready", onReady);
    this.events.addEventListener("change", (event) => {
      for (const change of parseChanges((event as MessageEvent<string>).data)) {
        onChange(change);
      }
    });
  }

  close(): void {
    this.events?.close();
    this.events = undefined;
  }
}

const parseChanges = (source: string): SourceFileChange[] => {
  let payload: unknown;
  try {
    payload = JSON.parse(source);
  } catch {
    return [];
  }
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("files" in payload) ||
    !Array.isArray(payload.files)
  ) {
    return [];
  }
  const changes: SourceFileChange[] = [];
  for (const file of payload.files) {
    if (typeof file !== "object" || file === null) {
      continue;
    }
    const path = "path" in file ? file.path : undefined;
    const revision = "revision" in file ? file.revision : undefined;
    if (
      (path === "index.html" || path === "app.css") &&
      (typeof revision === "string" || revision === null)
    ) {
      changes.push({ path, revision });
    }
  }
  return changes;
};
