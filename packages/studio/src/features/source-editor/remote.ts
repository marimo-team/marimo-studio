import type { SourceName } from "@marimo-studio/protocol/source-events";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";

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
  write(view: string, name: SourceName, content: string, revision: string): Promise<string>;
}

export class RevisionConflict extends Error {
  constructor(readonly revision: string) {
    super("Source revision changed");
  }
}

const responseJson = async (response: Response) => jsonValueSchema.parse(await response.json());

const responseErrorMessage = async (response: Response, fallback: string): Promise<string> => {
  try {
    return parseErrorResponse(await responseJson(response)).message ?? fallback;
  } catch {
    return fallback;
  }
};

export const createSourceRemote = (
  supportUrl: (view: string) => string,
  serverToken: string,
): SourceRemote => {
  const url = (view: string, name: SourceName) =>
    appendUrlPath(supportUrl(view), `source/${name}`, globalThis.location.href);
  return {
    async read(view, name) {
      const response = await fetch(url(view, name), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Could not read ${name} (${response.status})`);
      }
      const revision = response.headers.get("ETag")?.replace(/^W\//, "").replace(/^"|"$/g, "");
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
        const body = await responseJson(response);
        throw new RevisionConflict(parseErrorResponse(body).revision ?? "");
      }
      if (!response.ok) {
        throw new Error(
          await responseErrorMessage(response, `Could not save ${name} (${response.status})`),
        );
      }
      const next = response.headers.get("ETag")?.replace(/^W\//, "").replace(/^"|"$/g, "");
      if (!next) {
        throw new Error(`${name} save did not include an ETag`);
      }
      return next;
    },
  };
};
