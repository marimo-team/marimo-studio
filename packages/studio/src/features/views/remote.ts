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

import { responseErrorMessage } from "../../shared/errors.ts";

export interface ViewRemote {
  list(signal?: AbortSignal): Promise<ViewList>;
  create(name: string, starter: string, catalogGeneration: string): Promise<CreatedView>;
  remove(name: string, catalogGeneration: string, viewGeneration: string): Promise<DeletedView>;
}

const responseJson = async (response: Response) => jsonValueSchema.parse(await response.json());

export const createViewRemote = (viewsUrl: string, serverToken: string): ViewRemote => ({
  async list(signal) {
    const response = await fetch(viewsUrl, { cache: "no-store", signal });
    if (!response.ok) {
      throw new Error(
        await responseErrorMessage(response, `Could not load views (${response.status})`),
      );
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
      throw new Error(
        await responseErrorMessage(response, `Could not create view (${response.status})`),
      );
    }
    return parseCreatedView(await responseJson(response));
  },

  async remove(name, catalogGeneration, viewGeneration) {
    const request = {
      catalog_generation: catalogGeneration,
      name,
      view_generation: viewGeneration,
    } satisfies DeleteViewRequest;
    const response = await fetch(appendUrlPath(viewsUrl, encodeURIComponent(name)), {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Server-Token": serverToken,
      },
      body: JSON.stringify(request),
    });
    if (!response.ok) {
      throw new Error(
        await responseErrorMessage(response, `Could not remove view (${response.status})`),
      );
    }
    return parseDeletedView(await responseJson(response));
  },
});
