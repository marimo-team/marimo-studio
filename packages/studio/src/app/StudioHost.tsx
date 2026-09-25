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
import { FirstViewToolbar } from "../features/views/FirstViewToolbar.tsx";
import { createViewRemote } from "../features/views/remote.ts";
import { preferredStarterId } from "../features/views/starters.ts";
import { useEditorWorkspace } from "../shared/editor-workspace.ts";
import { errorMessage } from "../shared/errors.ts";
import { StudioThemeProvider, useResolvedStudioTheme } from "../shared/theme.tsx";
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

const EDITOR_AUTHORITY_QUERY_KEYS = new Set([
  "file",
  STUDIO_CLIENT_QUERY_PARAM,
  SERVER_INSTANCE_QUERY_PARAM,
  "session_id",
  EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
]);
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

const editorAuthority = (source: string): string => {
  const url = new URL(source, globalThis.location.href);
  return `${url.origin}${url.pathname}\0${normalizedParameters(url.search, (key) => EDITOR_AUTHORITY_QUERY_KEYS.has(key))}`;
};

const trustedEditorAuthority = (configuredSource: string, retainedSource: string): string => {
  const full = editorAuthority(configuredSource);
  if (editorAuthority(retainedSource) !== full) {
    throw new Error("The configured Marimo editor does not match the retained editor.");
  }
  return full;
};

const retainedEditorSnapshot = (frame: HTMLIFrameElement, trusted: string): EditorSnapshot => {
  const editor = frame.contentWindow;
  const document = frame.contentDocument;
  if (!editor || !document) {
    throw new Error("The Marimo editor is unavailable.");
  }
  const url = new URL(editor.location.href);
  if (editorAuthority(url.href) !== trusted) {
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
  trusted: string,
  active: EditorSnapshot,
  source: string,
): void => {
  const configured = new URL(source, globalThis.location.href);
  if (
    editorAuthority(configured.href) !== trusted ||
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
  const nativeWorkspace = useEditorWorkspace(editorFrame, options.connectEditorWorkspace);
  useEffect(() => {
    if (!nativeWorkspace.workspace) return;
    const parent = editorFrame.parentElement;
    if (!parent) return;
    parent.style.top = "0";
    return () => {
      parent.style.removeProperty("top");
    };
  }, [editorFrame, nativeWorkspace.workspace]);
  useEffect(() => {
    if (bootstrap || !nativeWorkspace.bounds) return;
    const bounds = nativeWorkspace.bounds;
    nativeWorkspace.workspace?.placeNotebook({
      ...bounds,
      top: bounds.top + 34,
      height: bounds.height - 34,
    });
  }, [bootstrap, nativeWorkspace.bounds, nativeWorkspace.workspace]);
  const [initialActivation, setInitialActivation] = useState<ActiveViewRequest>();
  const [attempt, setAttempt] = useState(0);
  const [createdView, setCreatedView] = useState<string>();
  const [message, setMessage] = useState<string>();
  const [opening, setOpening] = useState(false);
  const [starter, setStarter] = useState("");
  const pendingView = useRef<string | null>(null);
  const [name, setName] = useState(host.state === "needs-view" ? host.defaultView : "dashboard");
  const theme = useResolvedStudioTheme(editorFrame, options.connectThemeFrame);
  const views = useMemo(
    () => createViewRemote(host.urls.views, host.serverToken),
    [host.serverToken, host.urls.views],
  );
  const initialCatalogGeneration = host.state === "needs-view" ? host.generation : "";
  const catalog = useMemo(
    () => new StarterCatalogController(() => views.list(), [], "", initialCatalogGeneration),
    [initialCatalogGeneration, views],
  );
  const catalogSnapshot = useControllerSnapshot(catalog);

  useEffect(() => {
    return () => catalog.dispose();
  }, [catalog]);

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
        const trustedEditor = trustedEditorAuthority(host.urls.editor, editorFrame.src);
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
        publishBootstrap(ready);
        const studioSource = new StudioRoutes(ready).studio(ready.selectedView);
        const studioQuery =
          activeEditor?.publicQuery ?? publicNotebookQuery(globalThis.location.search);
        globalThis.history.replaceState(
          globalThis.history.state,
          "",
          withPublicQuery(studioSource, studioQuery),
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
        editorWorkspace={nativeWorkspace.workspace}
        editorBounds={nativeWorkspace.bounds}
        initialActivation={initialActivation}
        onRetry={retry}
        {...options}
      />
    );
  }

  const selectedStarter = catalogSnapshot.starters.find((candidate) => candidate.id === starter);
  const createFirstView = async (event: FormEvent) => {
    event.preventDefault();
    if (opening) {
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
      let view = createdView;
      if (!view) {
        try {
          view = (await views.create(name, starter, catalogSnapshot.generation)).name;
        } catch (cause) {
          catalog.invalidate();
          await catalog.refresh();
          throw cause;
        }
      }
      setCreatedView(view);
      await openWorkspace(view);
    } catch (cause) {
      setOpening(false);
      setMessage(errorMessage(cause));
    }
  };

  return (
    <StudioThemeProvider theme={theme}>
      <div
        className="studio studio-empty"
        data-theme={theme}
        style={
          nativeWorkspace.bounds ? { position: "fixed", ...nativeWorkspace.bounds } : undefined
        }
      >
        <FirstViewToolbar
          onOpen={() => void catalog.ensure()}
          form={{
            busy: opening,
            message: message ? { state: "error", text: message } : undefined,
            name,
            submitLabel: createdView ? `Open ${createdView}` : "Create view",
            starter,
            starterCatalog: catalogSnapshot.state,
            starters: catalogSnapshot.starters,
            viewRoot: catalogSnapshot.viewRoot,
            onNameChange: setName,
            onRetryStarters: () => void catalog.ensure(),
            onStarterChange: setStarter,
            onSubmit: (event) => void createFirstView(event),
          }}
        />
      </div>
    </StudioThemeProvider>
  );
};
