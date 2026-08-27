import { parseEditorDocumentMutation } from "@marimo-studio/protocol/development-events";
import {
  FRAME_BRIDGE_MESSAGE_BOUNDS,
  isBoundedBrowserMessage,
} from "@marimo-studio/protocol/frame-bridge";

interface EditorDocumentMutationCallbacks {
  pending(generation: number, acknowledgement: MessagePort): void;
  reloaded(): void;
  saved(generation: number, succeeded: boolean): void;
  transactionApplied(generation: number, changed: boolean): void;
  transactionFailed(generation: number): void;
}

export const EDITOR_DOCUMENT_MUTATION_BRIDGE_ATTRIBUTE =
  "data-marimo-studio-document-mutation-bridge";

export const bindEditorDocumentMutations = (
  editor: HTMLIFrameElement,
  callbacks: EditorDocumentMutationCallbacks,
): (() => void) => {
  const receive = (event: MessageEvent<unknown>) => {
    if (event.origin !== globalThis.location.origin || event.source !== editor.contentWindow) {
      return;
    }
    const mutation = isBoundedBrowserMessage(event.data, FRAME_BRIDGE_MESSAGE_BOUNDS)
      ? parseEditorDocumentMutation(event.data)
      : undefined;
    const expectedPorts = mutation?.type === "marimo-studio:editor-document-mutation" ? 1 : 0;
    if (!mutation || event.ports.length !== expectedPorts) {
      for (const port of event.ports) {
        port.postMessage({
          schema: 1,
          type: "marimo-studio:editor-document-mutation-failed",
          generation: 0,
        });
        port.close();
      }
      return;
    }
    if (mutation.type === "marimo-studio:editor-document-transaction-applied") {
      callbacks.transactionApplied(mutation.generation, mutation.changed);
    } else if (mutation.type === "marimo-studio:editor-document-transaction-failed") {
      callbacks.transactionFailed(mutation.generation);
    } else if (mutation.type !== "marimo-studio:editor-document-mutation") {
      callbacks.saved(mutation.generation, mutation.type === "marimo-studio:editor-document-saved");
    } else {
      callbacks.pending(mutation.generation, event.ports[0]);
    }
  };
  const reloaded = () => callbacks.reloaded();
  editor.setAttribute(EDITOR_DOCUMENT_MUTATION_BRIDGE_ATTRIBUTE, "");
  editor.addEventListener("load", reloaded);
  globalThis.addEventListener("message", receive);
  return () => {
    globalThis.removeEventListener("message", receive);
    editor.removeEventListener("load", reloaded);
    editor.removeAttribute(EDITOR_DOCUMENT_MUTATION_BRIDGE_ATTRIBUTE);
  };
};
