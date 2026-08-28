import type { StudioHostBootstrap } from "@marimo-studio/protocol/studio-host";

import {
  parseActiveViewRequest,
  type ActiveViewRequest,
} from "@marimo-studio/protocol/development-events";
import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import {
  EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
  publicNotebookQuery,
  SERVER_INSTANCE_QUERY_PARAM,
  STUDIO_CLIENT_QUERY_PARAM,
} from "@marimo-studio/protocol/query";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import {
  parseStudioBootstrap,
  type StudioBootstrap,
} from "@marimo-studio/protocol/studio-bootstrap";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StarterCatalogController } from "../features/views/catalog.ts";
import { createViewRemote } from "../features/views/remote.ts";
import { StarterCatalogNotice } from "../features/views/StarterCatalogNotice.tsx";
import { StarterPlan } from "../features/views/StarterPlan.tsx";
import { preferredStarterId } from "../features/views/starters.ts";
import { errorMessage } from "../shared/errors.ts";
import { useControllerSnapshot } from "../shared/useControllerSnapshot.ts";
import { StudioRoutes } from "./routes.ts";
import { StudioApp, type StudioOptions } from "./StudioApp.tsx";
import { workspaceEventsUrl } from "./workspace-event-coordinator.ts";

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

const reloadRetainedEditor = (frame: HTMLIFrameElement, source: string): Promise<void> =>
  new Promise((resolve, reject) => {
    const loaded = () => resolve();
    frame.addEventListener("load", loaded, { once: true });
    try {
      frame.src = source;
    } catch (cause) {
      frame.removeEventListener("load", loaded);
      reject(cause);
    }
  });

const EDITOR_AUTHORITY_QUERY_KEYS = new Set([
  "file",
  STUDIO_CLIENT_QUERY_PARAM,
  SERVER_INSTANCE_QUERY_PARAM,
  "session_id",
  EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
]);
const LIVE_EDITOR_AUTHORITY_QUERY_KEYS = new Set(
  [...EDITOR_AUTHORITY_QUERY_KEYS].filter((key) => key !== "session_id"),
);
const EDITOR_QUERY_ATTEMPTS = 3;

const normalizedParameters = (
  search: string,
  include: (key: string) => boolean = () => true,
): string => {
  const parameters = new URLSearchParams();
  for (const [key, value] of new URLSearchParams(search)) {
    if (include(key)) {
      parameters.append(key, value);
    }
  }
  parameters.sort();
  return parameters.toString();
};

interface EditorSnapshot {
  readonly document: Document;
  readonly publicQuery: string;
  readonly publicState: string;
}

interface TrustedEditorAuthority {
  readonly full: string;
  readonly live: string;
  readonly session: string;
}

const editorAuthority = (source: string, keys: ReadonlySet<string>): string => {
  const url = new URL(source, globalThis.location.href);
  return `${url.origin}${url.pathname}\0${normalizedParameters(url.search, (key) => keys.has(key))}`;
};

const trustedEditorAuthority = (
  configuredSource: string,
  retainedSource: string,
): TrustedEditorAuthority => {
  const full = editorAuthority(configuredSource, EDITOR_AUTHORITY_QUERY_KEYS);
  if (editorAuthority(retainedSource, EDITOR_AUTHORITY_QUERY_KEYS) !== full) {
    throw new Error("The configured Marimo editor does not match the retained editor.");
  }
  const configured = new URL(configuredSource, globalThis.location.href);
  return {
    full,
    live: editorAuthority(configured.href, LIVE_EDITOR_AUTHORITY_QUERY_KEYS),
    session: normalizedParameters(configured.search, (key) => key === "session_id"),
  };
};

const retainedEditorSnapshot = (
  frame: HTMLIFrameElement,
  trusted: TrustedEditorAuthority,
): EditorSnapshot => {
  const editor = frame.contentWindow;
  const document = frame.contentDocument;
  if (!editor || !document) {
    throw new Error("The Marimo editor is unavailable.");
  }
  const url = new URL(editor.location.href);
  if (editorAuthority(url.href, LIVE_EDITOR_AUTHORITY_QUERY_KEYS) !== trusted.live) {
    throw new Error("The active Marimo editor changed while Studio opened.");
  }
  const liveSession = normalizedParameters(url.search, (key) => key === "session_id");
  if (liveSession && liveSession !== trusted.session) {
    throw new Error("The active Marimo editor changed while Studio opened.");
  }
  const publicQuery = publicNotebookQuery(url.search);
  return {
    document,
    publicQuery,
    publicState: normalizedParameters(publicQuery),
  };
};

const validateConfiguredEditor = (
  trusted: TrustedEditorAuthority,
  active: EditorSnapshot,
  source: string,
): void => {
  const configured = new URL(source, globalThis.location.href);
  if (
    editorAuthority(configured.href, EDITOR_AUTHORITY_QUERY_KEYS) !== trusted.full ||
    normalizedParameters(publicNotebookQuery(configured.search)) !== active.publicState
  ) {
    throw new Error("The configured Marimo editor does not match the active editor.");
  }
};

const withPublicQuery = (source: string, query: string): URL => {
  const url = new URL(source, globalThis.location.href);
  const existing = new Set(new URLSearchParams(publicNotebookQuery(url.search)).keys());
  for (const key of existing) {
    url.searchParams.delete(key);
  }
  for (const [key, value] of new URLSearchParams(query)) {
    url.searchParams.append(key, value);
  }
  return url;
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
  const [starter, setStarter] = useState("");
  const pendingView = useRef<string | null>(null);
  const initialization = useRef<HTMLElement>(null);
  const views = useMemo(
    () => createViewRemote(host.urls.views, host.serverToken),
    [host.serverToken, host.urls.views],
  );
  const catalog = useMemo(() => new StarterCatalogController(() => views.list()), [views]);
  const catalogSnapshot = useControllerSnapshot(catalog);

  useEffect(() => {
    return () => catalog.dispose();
  }, [catalog]);

  useEffect(() => {
    if (!bootstrap && host.state === "needs-view") {
      void catalog.ensure();
    }
  }, [bootstrap, catalog, host.state]);

  useEffect(() => {
    const blocked = !bootstrap && host.state === "needs-view";
    editorFrame.toggleAttribute("inert", blocked);
    if (blocked) {
      editorFrame.setAttribute("aria-hidden", "true");
      const frame = globalThis.requestAnimationFrame(() => initialization.current?.focus());
      return () => {
        globalThis.cancelAnimationFrame(frame);
        editorFrame.removeAttribute("inert");
        editorFrame.removeAttribute("aria-hidden");
      };
    }
    editorFrame.removeAttribute("aria-hidden");
    return;
  }, [bootstrap, editorFrame, host.state]);

  useEffect(() => {
    if (
      catalogSnapshot.starters.some(
        (candidate) => candidate.id === starter && candidate.availability.available,
      )
    ) {
      return;
    }
    setStarter(preferredStarterId(catalogSnapshot.starters, catalogSnapshot.defaultStarter));
  }, [catalogSnapshot.defaultStarter, catalogSnapshot.starters, starter]);

  const openWorkspace = useCallback(
    async (view: string, activation?: ActiveViewRequest) => {
      if (pendingView.current) {
        return false;
      }
      pendingView.current = view;
      setMessage(undefined);
      setOpening(true);
      try {
        const trustedEditor = activation
          ? trustedEditorAuthority(host.urls.editor, editorFrame.src)
          : undefined;
        let activeEditor = trustedEditor
          ? retainedEditorSnapshot(editorFrame, trustedEditor)
          : undefined;
        let ready: StudioBootstrap | undefined;
        for (let queryAttempt = 0; queryAttempt < EDITOR_QUERY_ATTEMPTS; queryAttempt += 1) {
          const url = activeEditor
            ? withPublicQuery(host.urls.bootstrap, activeEditor.publicQuery)
            : new URL(host.urls.bootstrap, globalThis.location.href);
          url.searchParams.set("marimo_studio_view", view);
          const response = await fetch(url, { cache: "no-store" });
          if (!response.ok) {
            throw new Error(await responseError(response));
          }
          const candidate = parseStudioBootstrap(await responseJson(response));
          if (!activeEditor || !trustedEditor) {
            ready = candidate;
            break;
          }
          const currentEditor = retainedEditorSnapshot(editorFrame, trustedEditor);
          if (currentEditor.document !== activeEditor.document) {
            throw new Error("The active Marimo editor changed while Studio opened.");
          }
          if (currentEditor.publicState !== activeEditor.publicState) {
            if (queryAttempt === EDITOR_QUERY_ATTEMPTS - 1) {
              throw new Error("The Marimo editor query kept changing while Studio opened.");
            }
            activeEditor = currentEditor;
            continue;
          }
          validateConfiguredEditor(trustedEditor, activeEditor, candidate.urls.editor);
          ready = candidate;
          break;
        }
        if (!ready) {
          throw new Error("The Studio workspace could not be opened.");
        }
        const editorSource = new URL(ready.urls.editor, globalThis.location.href).href;
        publishBootstrap(ready);
        const studioSource = new StudioRoutes(ready).studio(ready.selectedView);
        const studioQuery =
          activeEditor?.publicQuery ?? publicNotebookQuery(globalThis.location.search);
        globalThis.history.replaceState(
          globalThis.history.state,
          "",
          withPublicQuery(studioSource, studioQuery),
        );
        if (!activation) {
          await reloadRetainedEditor(editorFrame, editorSource);
        }
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
    [editorFrame, host.urls.bootstrap, host.urls.editor, publishBootstrap],
  );

  useEffect(() => {
    if (bootstrap) {
      return;
    }
    const events = new EventSource(workspaceEventsUrl(host.urls.events));
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

  const selectedStarter = catalogSnapshot.starters.find((candidate) => candidate.id === starter);
  const createFirstView = async (event: FormEvent) => {
    event.preventDefault();
    if (host.state !== "needs-view" || opening) {
      return;
    }
    setMessage(undefined);
    setOpening(true);
    try {
      if (!createdView && selectedStarter?.availability.available !== true) {
        throw new Error(
          selectedStarter?.availability.action ?? "Choose an available starting option.",
        );
      }
      const view = createdView ?? (await views.create(host.defaultView, starter)).name;
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
    <main
      ref={initialization}
      className="studio-initialization"
      data-studio-initialization=""
      tabIndex={-1}
    >
      <div className="studio-initialization-card">
        <span className="studio-initialization-eyebrow">Marimo Studio</span>
        <h1>Create the first page</h1>
        <p>
          Create <code>{host.defaultView}</code> to open the notebook, page source, and preview
          together.
        </p>
        <form onSubmit={(event) => void createFirstView(event)}>
          <StarterCatalogNotice
            catalog={catalogSnapshot.state}
            empty={catalogSnapshot.starters.length === 0}
            onRetry={() => void catalog.ensure()}
          />
          <label htmlFor="studio-initial-starter">Start with</label>
          <select
            id="studio-initial-starter"
            value={starter}
            aria-busy={catalogSnapshot.state.phase === "loading"}
            disabled={opening || catalogSnapshot.starters.length === 0}
            onChange={(event) => setStarter(event.target.value)}
          >
            {catalogSnapshot.starters.map((candidate) => (
              <option
                key={candidate.id}
                value={candidate.id}
                disabled={!candidate.availability.available}
              >
                {candidate.title}
              </option>
            ))}
          </select>
          {catalogSnapshot.starters.length > 0 ? (
            <div className="studio-initial-starter-plans" aria-label="Starting options">
              {catalogSnapshot.starters.map((candidate) => (
                <section key={candidate.id} data-selected={candidate.id === starter || undefined}>
                  <strong>{candidate.title}</strong>
                  <StarterPlan starter={candidate} />
                </section>
              ))}
            </div>
          ) : null}
          <button
            type="submit"
            disabled={opening || (!createdView && selectedStarter?.availability.available !== true)}
          >
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
