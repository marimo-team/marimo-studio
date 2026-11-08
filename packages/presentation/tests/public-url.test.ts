import "./framed-document.ts";
import type { PublicUrlMessage } from "@marimo-studio/protocol/preview-messages";

import { afterEach, beforeEach, expect, test, vi } from "vite-plus/test";

import { setActiveDocumentLifecycleId } from "../src/document/document-lifecycle-id.ts";
import { bindWrapperPublicUrl, publicUrl } from "../src/document/public-url.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: `${globalThis.location.origin}/_marimo-studio/views/dashboard`,
  version: "test-version",
  revision: "presentation-revision",
  runtime: "server",
  runtimeExplicit: true,
  replay: false,
};

const mintedDocument = "/_marimo-studio/presentation/d.token/dashboard/";
const privateQuery =
  "session_id=s_abc123&marimo_studio_client=client&marimo_studio_renewal=d.token&marimo_studio_handoff=h&access_token=secret";

const wrapper = {};
let unbind: () => void;

const answer = (url: string, lifecycleId = 7, view = "dashboard"): PublicUrlMessage => ({
  type: "marimo-studio:public-url",
  lifecycleId,
  view,
  url,
});

const receive = (data: PublicUrlMessage, source = wrapper) => {
  const event = new MessageEvent("message", { origin: globalThis.location.origin, data });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

beforeEach(() => {
  vi.stubGlobal("parent", wrapper);
  setActiveDocumentLifecycleId(7);
  commitRuntimeConfig(runtimeConfig({ publicRootUrl: "https://hub.example/s/f3a9/?file=a.py" }));
  unbind = bindWrapperPublicUrl();
});

afterEach(() => {
  unbind();
  vi.unstubAllGlobals();
  globalThis.history.replaceState({}, "", "/");
});

test("a presentation document answers with the public view address", () => {
  globalThis.history.replaceState({}, "", `${mintedDocument}?${privateQuery}&region=emea#details`);

  expect(publicUrl()).toBe(
    "https://hub.example/s/f3a9/dashboard/?file=a.py&region=emea&runtime=server#details",
  );
});

test("a static export answers with its own address without private parameters", () => {
  commitRuntimeConfig(runtimeConfig({ presentationSessionId: undefined }));
  globalThis.history.replaceState({}, "", `/export/report/?${privateQuery}&region=emea#details`);

  expect(publicUrl()).toBe(`${globalThis.location.origin}/export/report/?region=emea#details`);
});

test("the wrapper's address answers for the location it describes", () => {
  globalThis.history.replaceState({}, "", `${mintedDocument}?region=emea#details`);

  receive(answer("https://public.example/dashboard/?region=emea#details"));

  expect(publicUrl()).toBe("https://public.example/dashboard/?region=emea#details");
});

test("a location write reads as the new address before the wrapper answers", () => {
  globalThis.history.replaceState({}, "", `${mintedDocument}?region=emea`);
  receive(answer("https://public.example/dashboard/?region=emea"));

  globalThis.history.replaceState({}, "", `${mintedDocument}?region=apac#details`);

  expect(publicUrl()).toBe(
    "https://hub.example/s/f3a9/dashboard/?file=a.py&region=apac&runtime=server#details",
  );
});

test("an in-place view switch reads as the new view before the wrapper answers", () => {
  globalThis.history.replaceState({}, "", `${mintedDocument}?region=emea`);
  receive(answer("https://public.example/dashboard/?region=emea"));

  commitRuntimeConfig(
    runtimeConfig({ view: "report", publicRootUrl: "https://hub.example/s/f3a9/?file=a.py" }),
  );

  expect(publicUrl()).toBe(
    "https://hub.example/s/f3a9/report/?file=a.py&region=emea&runtime=server",
  );
});

test("an answer for another document or from another window is ignored", () => {
  globalThis.history.replaceState({}, "", mintedDocument);
  const staleUrl = "https://public.example/dashboard/";

  receive(answer(staleUrl, 8));
  receive(answer(staleUrl), {});

  expect(publicUrl()).toBe("https://hub.example/s/f3a9/dashboard/?file=a.py&runtime=server");
});
