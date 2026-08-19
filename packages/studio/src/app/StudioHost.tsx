import type { StudioHostBootstrap } from "@marimo-studio/protocol/studio-host";

import {
  parseActiveViewRequest,
  type ActiveViewRequest,
} from "@marimo-studio/protocol/development-events";
import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import {
  parseStudioBootstrap,
  type StudioBootstrap,
} from "@marimo-studio/protocol/studio-bootstrap";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createViewRemote } from "../features/views/remote.ts";
import { errorMessage } from "../shared/errors.ts";
import { StudioRoutes } from "./routes.ts";
import { StudioApp, type StudioOptions } from "./StudioApp.tsx";

interface StudioHostProps extends StudioOptions {
  editorFrame: HTMLIFrameElement;
  host: StudioHostBootstrap;
  initialBootstrap?: StudioBootstrap;
  publishBootstrap: (bootstrap: StudioBootstrap) => void;
}

const responseJson = async (response: Response) => jsonValueSchema.parse(await response.json());

const responseError = async (response: Response): Promise<string> => {
  try {
    return (
      parseErrorResponse(await responseJson(response)).message ??
      `Studio workspace request failed (${response.status})`
    );
  } catch {
    return `Studio workspace request failed (${response.status})`;
  }
};

export const StudioHost = ({
  editorFrame,
  host,
  initialBootstrap,
  publishBootstrap,
  ...options
}: StudioHostProps) => {
  const [bootstrap, setBootstrap] = useState(initialBootstrap);
  const [initialActivation, setInitialActivation] = useState<ActiveViewRequest>();
  const [attempt, setAttempt] = useState(0);
  const [createdView, setCreatedView] = useState<string>();
  const [message, setMessage] = useState<string>();
  const [opening, setOpening] = useState(false);
  const pendingView = useRef<string | null>(null);
  const views = useMemo(
    () => createViewRemote(host.urls.views, host.serverToken),
    [host.serverToken, host.urls.views],
  );

  const openWorkspace = useCallback(
    async (view: string, activation?: ActiveViewRequest) => {
      if (pendingView.current) {
        return false;
      }
      pendingView.current = view;
      setMessage(undefined);
      setOpening(true);
      try {
        const url = new URL(host.urls.bootstrap, globalThis.location.href);
        url.searchParams.set("marimo_studio_view", view);
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(await responseError(response));
        }
        const ready = parseStudioBootstrap(await responseJson(response));
        publishBootstrap(ready);
        globalThis.history.replaceState(
          globalThis.history.state,
          "",
          new StudioRoutes(ready).studio(ready.selectedView),
        );
        setInitialActivation(activation);
        setAttempt((current) => current + 1);
        setBootstrap(ready);
        return true;
      } catch (cause) {
        pendingView.current = null;
        setOpening(false);
        setMessage(errorMessage(cause));
        return false;
      }
    },
    [host.urls.bootstrap, publishBootstrap],
  );

  useEffect(() => {
    if (bootstrap) {
      return;
    }
    const events = new EventSource(host.urls.events);
    events.addEventListener("activate", (event) => {
      const payload = parseActiveViewRequest(
        event instanceof MessageEvent ? String(event.data) : "",
      );
      if (payload) {
        void openWorkspace(payload.view, payload);
      }
    });
    return () => events.close();
  }, [bootstrap, host.urls.events, openWorkspace]);

  if (bootstrap) {
    const retry = () => {
      const view = bootstrap.selectedView;
      pendingView.current = null;
      setBootstrap(undefined);
      setInitialActivation(undefined);
      setMessage(undefined);
      setOpening(false);
      void openWorkspace(view);
    };
    return (
      <StudioApp
        key={attempt}
        bootstrap={bootstrap}
        editorFrame={editorFrame}
        initialActivation={initialActivation}
        onRetry={retry}
        {...options}
      />
    );
  }

  const createFirstView = async (event: FormEvent) => {
    event.preventDefault();
    if (host.state !== "needs-view" || opening) {
      return;
    }
    setMessage(undefined);
    setOpening(true);
    try {
      const view = createdView ?? (await views.create(host.defaultView)).name;
      setCreatedView(view);
      await openWorkspace(view);
    } catch (cause) {
      setOpening(false);
      setMessage(errorMessage(cause));
    }
  };

  if (host.state !== "needs-view" && !opening && !message) {
    return null;
  }

  if (host.state !== "needs-view") {
    return (
      <main className="studio-host-status" role={message ? "alert" : "status"}>
        {message ?? "Opening Studio"}
      </main>
    );
  }

  return (
    <main className="studio-initialization" data-studio-initialization="">
      <div className="studio-initialization-card">
        <span className="studio-initialization-eyebrow">Marimo Studio</span>
        <h1>Create the first view</h1>
        <p>
          This notebook is configured for Studio. Create <code>{host.defaultView}</code> to open the
          authoring workspace.
        </p>
        <form onSubmit={(event) => void createFirstView(event)}>
          <button type="submit" disabled={opening}>
            {createdView ? `Open ${createdView}` : `Create ${host.defaultView}`}
          </button>
          <p role={message ? "alert" : "status"} aria-live="polite">
            {message ?? (opening ? "Opening Studio…" : "")}
          </p>
        </form>
      </div>
    </main>
  );
};
