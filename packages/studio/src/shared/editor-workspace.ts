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
    const connection = connect(frame, setBounds, (open) => {
      frame.toggleAttribute("data-native-dialog", open);
      if (root) root.inert = open || wasInert;
    });
    setWorkspace(connection);
    return () => {
      connection.close();
      frame.removeAttribute("data-native-dialog");
      if (root) root.inert = wasInert;
    };
  }, [connect, frame]);
  return { bounds, workspace };
};
