import { parseErrorResponse } from "@marimo-studio/protocol/errors";
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

const errorMessage = async (response: Response, fallback: string): Promise<string> => {
  const payload: unknown = await response.json().catch(() => undefined);
  return parseErrorResponse(payload).message ?? `${fallback} (${response.status})`;
};

export const createViewRemote = (viewsUrl: string, serverToken: string): ViewRemote => ({
  async list() {
    const response = await fetch(viewsUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not load views"));
    }
    return parseViewList(await response.json());
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
    return parseCreatedView(await response.json());
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
    return parseDeletedView(await response.json());
  },
});
