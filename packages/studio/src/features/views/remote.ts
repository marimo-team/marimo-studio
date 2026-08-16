import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import {
  parseCreatedView,
  parseDeletedView,
  parseViewList,
  type CreatedView,
  type DeletedView,
  type ViewList,
} from "@marimo-studio/protocol/views";

export interface ViewRemote {
  list(): Promise<ViewList>;
  create(name: string): Promise<CreatedView>;
  remove(name: string): Promise<DeletedView>;
}

const responseJson = async (response: Response) => jsonValueSchema.parse(await response.json());

const errorMessage = async (response: Response, fallback: string): Promise<string> => {
  const message = `${fallback} (${response.status})`;
  try {
    return parseErrorResponse(await responseJson(response)).message ?? message;
  } catch {
    return message;
  }
};

export const createViewRemote = (viewsUrl: string, serverToken: string): ViewRemote => ({
  async list() {
    const response = await fetch(viewsUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not load views"));
    }
    return parseViewList(await responseJson(response));
  },

  async create(name) {
    const response = await fetch(viewsUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Server-Token": serverToken,
      },
      body: JSON.stringify({ name }),
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not create view"));
    }
    return parseCreatedView(await responseJson(response));
  },

  async remove(name) {
    const response = await fetch(
      appendUrlPath(viewsUrl, encodeURIComponent(name), globalThis.location.href),
      {
        method: "DELETE",
        headers: { "Marimo-Server-Token": serverToken },
      },
    );
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not remove view"));
    }
    return parseDeletedView(await responseJson(response));
  },
});
