import type { SourceName } from "@marimo-studio/protocol/source-events";

import { type RefCallback, useCallback, useEffect, useMemo, useRef } from "react";

import type { SourceController, SourceSnapshot } from "./controller.ts";
import type { SourceEditorHandle } from "./SourceEditor.tsx";

import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";
import { sourceTabForKey } from "./files.ts";

interface EditorActions {
  change: (content: string) => void;
  save: () => void;
}

export interface SourcePaneModel {
  activeDocument: SourceSnapshot["documents"][SourceName];
  editorActions: Readonly<Record<SourceName, EditorActions>>;
  editorRefs: Readonly<Record<SourceName, RefCallback<SourceEditorHandle>>>;
  snapshot: SourceSnapshot;
  tabKeyDown: (name: SourceName, key: string) => boolean;
  tabRef: (name: SourceName) => RefCallback<HTMLButtonElement>;
  selectTab: (name: SourceName) => void;
}

export const useSourcePane = (controller: SourceController, visible: boolean): SourcePaneModel => {
  const snapshot = useControllerSnapshot(controller);
  const editors = useRef(new Map<SourceName, SourceEditorHandle>());
  const tabs = useRef(new Map<SourceName, HTMLButtonElement>());
  const pendingHtmlFocus = useRef<number | undefined>(undefined);
  const previousFocusRequest = useRef(snapshot.focusRequest);

  const registerEditor = useCallback((name: SourceName, handle: SourceEditorHandle | null) => {
    if (handle) {
      editors.current.set(name, handle);
    } else {
      editors.current.delete(name);
    }
    if (name === "index.html" && handle && pendingHtmlFocus.current !== undefined) {
      pendingHtmlFocus.current = undefined;
      handle.focus();
    }
  }, []);
  const editorRefs = useMemo<Readonly<Record<SourceName, RefCallback<SourceEditorHandle>>>>(
    () => ({
      "app.css": (handle) => registerEditor("app.css", handle),
      "index.html": (handle) => registerEditor("index.html", handle),
    }),
    [registerEditor],
  );
  const tabRefs = useMemo<Readonly<Record<SourceName, RefCallback<HTMLButtonElement>>>>(
    () => ({
      "app.css": (element) => {
        if (element) {
          tabs.current.set("app.css", element);
        } else {
          tabs.current.delete("app.css");
        }
      },
      "index.html": (element) => {
        if (element) {
          tabs.current.set("index.html", element);
        } else {
          tabs.current.delete("index.html");
        }
      },
    }),
    [],
  );
  const editorActions = useMemo<Readonly<Record<SourceName, EditorActions>>>(
    () => ({
      "app.css": {
        change: (content) => controller.edit("app.css", content),
        save: () => controller.save("app.css"),
      },
      "index.html": {
        change: (content) => controller.edit("index.html", content),
        save: () => controller.save("index.html"),
      },
    }),
    [controller],
  );

  useEffect(() => {
    if (snapshot.focusRequest === previousFocusRequest.current) {
      return;
    }
    previousFocusRequest.current = snapshot.focusRequest;
    pendingHtmlFocus.current = snapshot.focusRequest;
    const frame = globalThis.requestAnimationFrame(() => {
      const handle = editors.current.get("index.html");
      if (handle && pendingHtmlFocus.current === snapshot.focusRequest) {
        pendingHtmlFocus.current = undefined;
        handle.focus();
      }
    });
    return () => globalThis.cancelAnimationFrame(frame);
  }, [snapshot.focusRequest]);

  useEffect(() => {
    if (visible) {
      editors.current.forEach((editor) => editor.requestMeasure());
    }
  }, [visible]);

  const selectTab = useCallback((name: SourceName) => controller.activate(name), [controller]);
  const tabKeyDown = useCallback(
    (name: SourceName, key: string): boolean => {
      const next = sourceTabForKey(name, key);
      if (!next) {
        return false;
      }
      controller.activate(next);
      globalThis.requestAnimationFrame(() => tabs.current.get(next)?.focus());
      return true;
    },
    [controller],
  );
  const tabRef = useCallback((name: SourceName) => tabRefs[name], [tabRefs]);

  return {
    activeDocument: snapshot.documents[snapshot.active],
    editorActions,
    editorRefs,
    selectTab,
    snapshot,
    tabKeyDown,
    tabRef,
  };
};
