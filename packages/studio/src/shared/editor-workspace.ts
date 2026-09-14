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
) => EditorWorkspace;

export const useEditorWorkspace = (
  frame: HTMLIFrameElement,
  connect?: EditorWorkspaceConnector,
) => {
  const [bounds, setBounds] = useState<EditorRectangle>();
  const [workspace, setWorkspace] = useState<EditorWorkspace>();
  useEffect(() => {
    if (!connect) return;
    const connection = connect(frame, setBounds);
    setWorkspace(connection);
    return () => connection.close();
  }, [connect, frame]);
  return { bounds, workspace };
};
