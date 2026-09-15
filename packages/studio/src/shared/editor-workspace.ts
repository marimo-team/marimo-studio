import { useEffect, useState } from "react";

export interface EditorRectangle {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface EditorWorkspace {
  placeNotebook: (rectangle: EditorRectangle | undefined) => void;
  close: () => void;
}

export type EditorWorkspaceConnector = (
  frame: HTMLIFrameElement,
  onBounds: (bounds: EditorRectangle | undefined) => void,
  onDialog: (open: boolean) => void,
  onNotification: (bounds: EditorRectangle | undefined) => void,
) => EditorWorkspace;

export const useEditorWorkspace = (
  frame: HTMLIFrameElement,
  connect?: EditorWorkspaceConnector,
) => {
  const [bounds, setBounds] = useState<EditorRectangle>();
  const [workspace, setWorkspace] = useState<EditorWorkspace>();
  useEffect(() => {
    if (!connect) return;
    const root = frame.ownerDocument.getElementById("marimo-studio-root");
    const wasInert = root?.inert ?? false;
    const originalClip = root?.style.clipPath ?? "";
    const connection = connect(
      frame,
      setBounds,
      (open) => {
        frame.toggleAttribute("data-native-dialog", open);
        if (root) root.inert = open || wasInert;
      },
      (notification) => {
        if (!root) return;
        if (!notification) {
          root.style.clipPath = originalClip;
          return;
        }
        const origin = root.getBoundingClientRect();
        const editor = frame.getBoundingClientRect();
        const left = editor.left + notification.left - origin.left;
        const top = editor.top + notification.top - origin.top;
        const right = left + notification.width;
        const bottom = top + notification.height;
        // Let the native notification receive paint and pointer events through
        // Studio's panes while the rest of the workspace remains interactive.
        root.style.clipPath = `path(evenodd, "M 0 0 H ${origin.width} V ${origin.height} H 0 Z M ${left} ${top} H ${right} V ${bottom} H ${left} Z")`;
      },
    );
    setWorkspace(connection);
    return () => {
      connection.close();
      frame.removeAttribute("data-native-dialog");
      if (root) {
        root.inert = wasInert;
        root.style.clipPath = originalClip;
      }
    };
  }, [connect, frame]);
  return { bounds, workspace };
};
