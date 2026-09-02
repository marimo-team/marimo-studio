import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";
import type { ViewProject } from "@marimo-studio/protocol/view-project";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import { parseViewProject } from "@marimo-studio/protocol/view-project";

export interface RemoteSource {
  content: string;
  revision: string;
  catalogGeneration?: string;
  viewGeneration?: string;
}

export interface SourceConflict {
  kind: "revision" | "read-only" | "orphan";
  local: string;
  remote: RemoteSource;
  externalRecovery?: string;
}

export interface SourceRemote {
  project(view: string): Promise<ViewProject>;
  read(view: string, path: SourceDocumentPath): Promise<RemoteSource>;
  write(
    view: string,
    path: SourceDocumentPath,
    content: string,
    revision: string,
    catalogGeneration: string,
    viewGeneration: string,
  ): Promise<string>;
}

export class RevisionConflict extends Error {
  constructor(
    readonly revision: string,
    readonly externalRecovery?: string,
  ) {
    super("Source revision changed");
  }
}

const responseJson = async (response: Response) => jsonValueSchema.parse(await response.json());

const responseErrorMessage = async (response: Response, fallback: string): Promise<string> => {
  try {
    const error = parseErrorResponse(await responseJson(response));
    const message = error.message ?? fallback;
    return error.hint ? `${message} ${error.hint}` : message;
  } catch {
    return fallback;
  }
};

export const createSourceRemote = (
  supportUrl: (view: string) => string,
  serverToken: string,
): SourceRemote => {
  const sourceUrl = (view: string, path: SourceDocumentPath) => {
    const encoded = path.split("/").map(encodeURIComponent).join("/");
    return appendUrlPath(supportUrl(view), `source/${encoded}`, globalThis.location.href);
  };
  return {
    async project(view) {
      const response = await fetch(
        appendUrlPath(supportUrl(view), "project", globalThis.location.href),
        { cache: "no-store" },
      );
      if (!response.ok) {
        throw new Error(
          await responseErrorMessage(response, `Could not inspect ${view} (${response.status})`),
        );
      }
      return parseViewProject(await responseJson(response));
    },
    async read(view, path) {
      const response = await fetch(sourceUrl(view, path), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(
          await responseErrorMessage(response, `Could not read ${path} (${response.status})`),
        );
      }
      const revision = response.headers.get("ETag")?.replace(/^W\//, "").replace(/^"|"$/g, "");
      if (!revision) {
        throw new Error(`${path} response did not include an ETag`);
      }
      const catalogGeneration = response.headers.get("Marimo-Studio-Catalog-Generation");
      const viewGeneration = response.headers.get("Marimo-Studio-View-Generation");
      if (catalogGeneration === null && viewGeneration === null) {
        return { content: await response.text(), revision };
      }
      if (catalogGeneration === null || viewGeneration === null) {
        throw new Error(`${path} response included an incomplete source owner`);
      }
      if (!/^[0-9a-f]{64}$/.test(catalogGeneration) || !/^[0-9a-f]{64}$/.test(viewGeneration)) {
        throw new Error(`${path} response included an invalid source owner`);
      }
      const source: RemoteSource = {
        content: await response.text(),
        revision,
      };
      source.catalogGeneration = catalogGeneration;
      source.viewGeneration = viewGeneration;
      return source;
    },
    async write(view, path, content, revision, catalogGeneration, viewGeneration) {
      const response = await fetch(sourceUrl(view, path), {
        method: "PUT",
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "If-Match": `"${revision}"`,
          "Marimo-Studio-Catalog-Generation": catalogGeneration,
          "Marimo-Server-Token": serverToken,
          "Marimo-Studio-View-Generation": viewGeneration,
        },
        body: content,
      });
      if (response.status === 412) {
        const body = await responseJson(response);
        const conflict = parseErrorResponse(body);
        throw new RevisionConflict(conflict.revision ?? "", conflict.external_recovery);
      }
      if (!response.ok) {
        throw new Error(
          await responseErrorMessage(response, `Could not save ${path} (${response.status})`),
        );
      }
      const next = response.headers.get("ETag")?.replace(/^W\//, "").replace(/^"|"$/g, "");
      if (!next) {
        throw new Error(`${path} save did not include an ETag`);
      }
      return next;
    },
  };
};
