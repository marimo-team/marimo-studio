export type SourceName = "index.html" | "app.css";

export interface RemoteSource {
  content: string;
  revision: string;
}

export interface SourceConflict {
  local: string;
  remote: RemoteSource;
}

export interface SourceRemote {
  read(view: string, name: SourceName): Promise<RemoteSource>;
  write(
    view: string,
    name: SourceName,
    content: string,
    revision: string,
  ): Promise<string>;
}

export class RevisionConflict extends Error {
  constructor(readonly revision: string) {
    super("Source revision changed");
  }
}

export const createSourceRemote = (
  supportPrefix: string,
  serverToken: string,
): SourceRemote => {
  const url = (view: string, name: SourceName) =>
    `${supportPrefix}/${encodeURIComponent(view)}/source/${name}`;
  return {
    async read(view, name) {
      const response = await fetch(url(view, name), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Could not read ${name} (${response.status})`);
      }
      const revision = response.headers.get("ETag")?.replace(/^W\//, "")
        .replace(/^"|"$/g, "");
      if (!revision) {
        throw new Error(`${name} response did not include an ETag`);
      }
      return { content: await response.text(), revision };
    },
    async write(view, name, content, revision) {
      const response = await fetch(url(view, name), {
        method: "PUT",
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "If-Match": `"${revision}"`,
          "Marimo-Server-Token": serverToken,
        },
        body: content,
      });
      if (response.status === 412) {
        const body = await response.json() as { revision?: unknown };
        throw new RevisionConflict(
          typeof body.revision === "string" ? body.revision : "",
        );
      }
      if (!response.ok) {
        const body = await response.json().catch(() => null) as {
          message?: unknown;
        } | null;
        throw new Error(
          body && typeof body.message === "string"
            ? body.message
            : `Could not save ${name} (${response.status})`,
        );
      }
      const next = response.headers.get("ETag")?.replace(/^W\//, "")
        .replace(/^"|"$/g, "");
      if (!next) {
        throw new Error(`${name} save did not include an ETag`);
      }
      return next;
    },
  };
};
