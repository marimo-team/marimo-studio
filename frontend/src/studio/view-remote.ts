export interface ViewList {
  schema: 1;
  default_view: string;
  views: string[];
}

export interface CreatedView {
  schema: 1;
  name: string;
}

export interface DeletedView extends ViewList {
  name: string;
}

export interface ViewRemote {
  list(): Promise<ViewList>;
  create(name: string): Promise<CreatedView>;
  remove(name: string): Promise<DeletedView>;
}

const errorMessage = async (
  response: Response,
  fallback: string,
): Promise<string> => {
  const payload = await response.json().catch(() => null) as {
    message?: unknown;
  } | null;
  return payload && typeof payload.message === "string"
    ? payload.message
    : `${fallback} (${response.status})`;
};

const parseViewList = (payload: unknown): ViewList => {
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("schema" in payload) ||
    payload.schema !== 1 ||
    !("default_view" in payload) ||
    typeof payload.default_view !== "string" ||
    !("views" in payload) ||
    !Array.isArray(payload.views) ||
    !payload.views.every((view) => typeof view === "string") ||
    !payload.views.includes(payload.default_view)
  ) {
    throw new Error("The server returned an invalid view list.");
  }
  return payload as ViewList;
};

export const createViewRemote = (
  viewsUrl: string,
  serverToken: string,
): ViewRemote => ({
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
    const payload = await response.json() as Partial<CreatedView>;
    if (payload.schema !== 1 || typeof payload.name !== "string") {
      throw new Error("The server returned an invalid created view.");
    }
    return payload as CreatedView;
  },

  async remove(name) {
    const response = await fetch(`${viewsUrl}/${encodeURIComponent(name)}`, {
      method: "DELETE",
      headers: { "Marimo-Server-Token": serverToken },
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response, "Could not remove view"));
    }
    const payload = await response.json();
    const views = parseViewList(payload);
    if (
      typeof payload !== "object" ||
      payload === null ||
      !("name" in payload) ||
      typeof payload.name !== "string"
    ) {
      throw new Error("The server returned an invalid removed view.");
    }
    return { ...views, name: payload.name };
  },
});
