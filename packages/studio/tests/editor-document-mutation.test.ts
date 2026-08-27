import type { BrowserMessageInput } from "@marimo-studio/protocol/frame-bridge";

import { afterEach, expect, it, vi } from "vite-plus/test";

import {
  bindEditorDocumentMutations,
  EDITOR_DOCUMENT_MUTATION_BRIDGE_ATTRIBUTE,
} from "../src/app/editor-document-mutation.ts";

afterEach(() => {
  document.body.replaceChildren();
});

interface TestMessageSource {
  postMessage: ReturnType<typeof vi.fn>;
}

const dispatch = (
  source: TestMessageSource,
  data: BrowserMessageInput,
  ports: MessagePort[],
  origin = globalThis.location.origin,
) => {
  const event = new MessageEvent("message", { data, origin, ports });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

const testPort = () => {
  const channel = new MessageChannel();
  return {
    channel,
    port: channel.port1,
  };
};

it("admits document mutations from the exact editor bridge", () => {
  const editor = document.createElement("iframe");
  const source = { postMessage: vi.fn() };
  Object.defineProperty(editor, "contentWindow", { configurable: true, value: source });
  const callbacks = {
    pending: vi.fn(),
    reloaded: vi.fn(),
    saved: vi.fn(),
    transactionApplied: vi.fn(),
    transactionFailed: vi.fn(),
  };
  const stop = bindEditorDocumentMutations(editor, callbacks);
  const acknowledgement = testPort();

  expect(editor).toHaveAttribute(EDITOR_DOCUMENT_MUTATION_BRIDGE_ATTRIBUTE);
  dispatch(
    source,
    {
      schema: 1,
      type: "marimo-studio:editor-document-mutation",
      generation: 4,
    },
    [acknowledgement.port],
  );

  expect(callbacks.pending.mock.calls[0]?.[0]).toBe(4);
  expect(callbacks.pending.mock.calls[0]?.[1]).toBe(acknowledgement.port);
  dispatch(
    source,
    {
      schema: 1,
      type: "marimo-studio:editor-document-saved",
      generation: 4,
    },
    [],
  );
  expect(callbacks.saved).toHaveBeenCalledWith(4, true);
  dispatch(
    source,
    {
      schema: 1,
      type: "marimo-studio:editor-document-transaction-applied",
      generation: 4,
      changed: false,
    },
    [],
  );
  expect(callbacks.transactionApplied).toHaveBeenCalledWith(4, false);
  editor.dispatchEvent(new Event("load"));
  expect(callbacks.reloaded).toHaveBeenCalledOnce();
  stop();
  expect(editor).not.toHaveAttribute(EDITOR_DOCUMENT_MUTATION_BRIDGE_ATTRIBUTE);
  acknowledgement.channel.port2.close();
});

it("rejects malformed exact-editor messages and ignores other senders", async () => {
  const editor = document.createElement("iframe");
  const source = { postMessage: vi.fn() };
  const other = { postMessage: vi.fn() };
  Object.defineProperty(editor, "contentWindow", { configurable: true, value: source });
  const callbacks = {
    pending: vi.fn(),
    reloaded: vi.fn(),
    saved: vi.fn(),
    transactionApplied: vi.fn(),
    transactionFailed: vi.fn(),
  };
  const stop = bindEditorDocumentMutations(editor, callbacks);
  const malformed = testPort();
  const foreign = testPort();
  const message = {
    schema: 1,
    type: "marimo-studio:editor-document-mutation",
    generation: 7,
  };
  const rejected = new Promise<unknown>((resolve) => {
    malformed.channel.port2.onmessage = (event) => resolve(event.data);
    malformed.channel.port2.start();
  });

  dispatch(source, { ...message, extra: true }, [malformed.port]);
  dispatch(other, message, [foreign.port]);
  dispatch(source, message, [foreign.port], "https://other.invalid");

  await expect(rejected).resolves.toEqual({
    schema: 1,
    type: "marimo-studio:editor-document-mutation-failed",
    generation: 0,
  });
  expect(callbacks.pending).not.toHaveBeenCalled();
  stop();
  malformed.channel.port2.close();
  foreign.channel.port1.close();
  foreign.channel.port2.close();
});
