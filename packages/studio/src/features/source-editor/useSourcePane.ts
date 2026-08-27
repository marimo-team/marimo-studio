import type { SourceDocumentPath } from "@marimo-studio/protocol/source-documents";

import { type RefCallback, useCallback, useEffect, useRef } from "react";

import type { SourceController, SourceSnapshot } from "./controller.ts";
import type { SourceEditorHandle } from "./SourceEditor.tsx";

import { useControllerSnapshot } from "../../shared/useControllerSnapshot.ts";
import { sourceTabForKey } from "./tabs.ts";

const SOURCE_TAB_END_GUTTER = 4;

const revealSourceTab = (tab: HTMLButtonElement): void => {
  const scroller = tab.parentElement;
  if (!scroller) {
    return;
  }
  const tabBounds = tab.getBoundingClientRect();
  const scrollerBounds = scroller.getBoundingClientRect();
  if (tabBounds.left < scrollerBounds.left) {
    scroller.scrollLeft += tabBounds.left - scrollerBounds.left;
  } else if (tabBounds.right > scrollerBounds.right - SOURCE_TAB_END_GUTTER) {
    scroller.scrollLeft += tabBounds.right - scrollerBounds.right + SOURCE_TAB_END_GUTTER;
  }
};

export interface SourcePaneModel {
  activeDocument: SourceSnapshot["documents"][number] | undefined;
  editorRef: RefCallback<SourceEditorHandle>;
  focusEditor: () => void;
  snapshot: SourceSnapshot;
  tabKeyDown: (path: SourceDocumentPath, key: string) => boolean;
  tabRef: (path: SourceDocumentPath) => RefCallback<HTMLButtonElement>;
  selectTab: (path: SourceDocumentPath) => void;
  change: (content: string) => void;
  save: () => void;
}

export const useSourcePane = (controller: SourceController, visible: boolean): SourcePaneModel => {
  const snapshot = useControllerSnapshot(controller);
  const editor = useRef<SourceEditorHandle | null>(null);
  const tabs = useRef(new Map<SourceDocumentPath, HTMLButtonElement>());
  const pendingFocus = useRef<number | undefined>(undefined);
  const previousFocusRequest = useRef(snapshot.focusRequest);
  const paths = snapshot.documents.map(({ path }) => path);
  const activeDocument = snapshot.documents.find(({ path }) => path === snapshot.active);

  const editorRef = useCallback((handle: SourceEditorHandle | null) => {
    editor.current = handle;
    if (handle && pendingFocus.current !== undefined) {
      pendingFocus.current = undefined;
      handle.focus();
    }
  }, []);

  const focusEditor = useCallback(() => {
    pendingFocus.current = snapshot.focusRequest;
    if (editor.current) {
      pendingFocus.current = undefined;
      editor.current.focus();
    }
  }, [snapshot.focusRequest]);

  useEffect(() => {
    if (snapshot.focusRequest === previousFocusRequest.current) {
      return;
    }
    previousFocusRequest.current = snapshot.focusRequest;
    pendingFocus.current = snapshot.focusRequest;
    const frame = globalThis.requestAnimationFrame(() => {
      if (pendingFocus.current === snapshot.focusRequest) {
        pendingFocus.current = undefined;
        editor.current?.focus();
      }
    });
    return () => globalThis.cancelAnimationFrame(frame);
  }, [snapshot.focusRequest]);

  useEffect(() => {
    if (visible) {
      editor.current?.requestMeasure();
    }
  }, [visible, snapshot.active]);

  useEffect(() => {
    const active = snapshot.active;
    if (!active) {
      return;
    }
    const frame = globalThis.requestAnimationFrame(() => {
      const tab = tabs.current.get(active);
      if (tab) {
        revealSourceTab(tab);
      }
    });
    return () => globalThis.cancelAnimationFrame(frame);
  }, [snapshot.active]);

  const selectTab = useCallback(
    (path: SourceDocumentPath) => controller.activate(path),
    [controller],
  );
  const tabKeyDown = useCallback(
    (path: SourceDocumentPath, key: string): boolean => {
      const next = sourceTabForKey(paths, path, key);
      if (!next) {
        return false;
      }
      controller.activate(next);
      globalThis.requestAnimationFrame(() => {
        const tab = tabs.current.get(next);
        tab?.focus();
        if (tab) {
          revealSourceTab(tab);
        }
      });
      return true;
    },
    [controller, paths],
  );
  const tabRef = useCallback(
    (path: SourceDocumentPath): RefCallback<HTMLButtonElement> =>
      (element) => {
        if (element) {
          tabs.current.set(path, element);
        } else {
          tabs.current.delete(path);
        }
      },
    [],
  );
  const change = useCallback(
    (content: string) => {
      if (snapshot.active) {
        controller.edit(snapshot.active, content);
      }
    },
    [controller, snapshot.active],
  );
  const save = useCallback(() => {
    if (snapshot.active) {
      controller.save(snapshot.active);
    }
  }, [controller, snapshot.active]);

  return {
    activeDocument,
    change,
    editorRef,
    focusEditor,
    save,
    selectTab,
    snapshot,
    tabKeyDown,
    tabRef,
  };
};
