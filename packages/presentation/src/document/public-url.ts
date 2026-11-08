import {
  parsePreviewMessage,
  type PublicUrlMessage,
} from "@marimo-studio/protocol/preview-messages";
import { publicNotebookQuery } from "@marimo-studio/protocol/query";

import { getMountConfig, getRuntimeConfig } from "../runtime-config/index.ts";
import { activeDocumentLifecycleId } from "./document-lifecycle-id.ts";
import { isStudioParentMessage } from "./parent-bridge.ts";
import { publicViewUrl, setTrustedRuntimeQuery } from "./view-navigation.ts";

let wrapperAnswer: Pick<PublicUrlMessage, "url" | "view"> | undefined;

const documentPublicUrl = (): string => {
  const { hash, href, search } = globalThis.location;
  const config = getRuntimeConfig();
  const query = publicNotebookQuery(search);
  let target: URL;
  if (config.presentationSessionId === undefined) {
    target = new URL(href);
    target.search = query;
  } else {
    target = publicViewUrl(new URL(config.publicRootUrl), config.view, query);
    setTrustedRuntimeQuery(target, {
      id: config.runtime.id,
      explicit: getMountConfig().runtimeExplicit,
    });
  }
  target.hash = hash;
  return target.href;
};

// The wrapper answers each location report after a task boundary, and it learns
// of an in-place view switch after the document commits. Until the answer names
// the current view and location, the document's own address is the current one.
const describesCurrentDocument = ({ url, view }: NonNullable<typeof wrapperAnswer>): boolean => {
  const { hash, search } = new URL(url);
  return (
    view === getRuntimeConfig().view &&
    hash === globalThis.location.hash &&
    publicNotebookQuery(search) === publicNotebookQuery(globalThis.location.search)
  );
};

export const publicUrl = (): string =>
  wrapperAnswer !== undefined && describesCurrentDocument(wrapperAnswer)
    ? wrapperAnswer.url
    : documentPublicUrl();

export const bindWrapperPublicUrl = (): (() => void) => {
  const listener = (event: MessageEvent<unknown>) => {
    if (!isStudioParentMessage(event)) {
      return;
    }
    const message = parsePreviewMessage(event.data);
    if (
      message?.type === "marimo-studio:public-url" &&
      message.lifecycleId === activeDocumentLifecycleId()
    ) {
      wrapperAnswer = { url: message.url, view: message.view };
    }
  };
  globalThis.addEventListener("message", listener);
  return () => {
    globalThis.removeEventListener("message", listener);
    wrapperAnswer = undefined;
  };
};
