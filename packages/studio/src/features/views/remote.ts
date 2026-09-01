import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import {
  parseCreatedView,
  parseDeletedView,
  parseViewList,
  type CreateViewRequest,
  type CreatedView,
  type DeleteViewRequest,
  type DeletedView,
  type ViewList,
} from "@marimo-studio/protocol/views";

export interface ViewRemote {
  list(signal?: AbortSignal): Promise<ViewList>;
  create(name: string, starter: string, catalogGeneration: string): Promise<CreatedView>;
  remove(name: string, catalogGeneration: string, viewGeneration: string): Promise<DeletedView>;
}

const responseJson = async (response: Response) => jsonValueSchema.parse(await response.json());

const errorMessage = async (response: Response, fallback: string): Promise<string> => {
  const fallbackMessage = `${fallback} (${response.status})`;
  try {
    const error = parseErrorResponse(await responseJson(response));
    const message = error.message ?? fallbackMessage;
    return error.hint ? `${message} ${error.hint}` : message;
  } catch {
    return fallbackMessage;
  }
};

export const createViewRemote = (viewsUrl: string, serverToken: string): ViewRemote => ({
  async list(signal) {
    const response = await fetch(viewsUrl, { cache: "no-store", signal });
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not load views"));
    }
    return parseViewList(await responseJson(response));
  },

  async create(name, starter, catalogGeneration) {
    const request = {
      catalog_generation: catalogGeneration,
      name,
      starter,
    } satisfies CreateViewRequest;
    const response = await fetch(viewsUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Server-Token": serverToken,
      },
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not create view"));
    }
    return parseCreatedView(await responseJson(response));
  },

  async remove(name, catalogGeneration, viewGeneration) {
    const request = {
      catalog_generation: catalogGeneration,
      name,
      view_generation: viewGeneration,
    } satisfies DeleteViewRequest;
    const response = await fetch(
      appendUrlPath(viewsUrl, encodeURIComponent(name), globalThis.location.href),
      {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Server-Token": serverToken,
        },
        body: JSON.stringify(request),
      },
    );
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not remove view"));
    }
    return parseDeletedView(await responseJson(response));
  },
});
