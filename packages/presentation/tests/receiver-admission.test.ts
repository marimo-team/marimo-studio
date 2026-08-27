import { afterEach, expect, test, vi } from "vite-plus/test";

import { waitForReceiverAdmission } from "../src/document/receiver-admission.ts";
import { PresentationDocumentRetiredError } from "../src/document/session-startup.ts";

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/_marimo-studio/views/dashboard",
  version: "test-version",
  revision: "revision-old",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
  clientId: "client-123456789",
  lifecycleId: 7,
};

afterEach(() => {
  globalThis.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

const dispatch = (source: WindowProxy, revision: string, lifecycleId = 7): void => {
  const event = new MessageEvent("message", {
    data: {
      type: "marimo-studio:receiver-admitted",
      runtime: "server",
      lifecycleId,
      view: "dashboard",
      revision,
    },
    origin: globalThis.location.origin,
  });
  Object.defineProperty(event, "source", { value: source });
  globalThis.dispatchEvent(event);
};

test("Studio admission accepts only the current document identity", async () => {
  globalThis.history.replaceState(
    {},
    "",
    "/dashboard/?marimo_studio_client=client-123456789&marimo_studio_lifecycle=7",
  );
  const parent = globalThis.window;
  vi.stubGlobal("parent", parent);
  let revision = "revision-current";
  const admitted = waitForReceiverAdmission(
    {
      lifecycleId: 7,
      runtime: "server",
      view: "dashboard",
      revision: () => revision,
    },
    true,
  );
  let resolved = false;
  void admitted.then(() => {
    resolved = true;
  });

  dispatch(parent, "revision-current", 6);
  dispatch(parent, "revision-stale");
  await Promise.resolve();
  expect(resolved).toBe(false);

  revision = "revision-next";
  dispatch(parent, "revision-current");
  await Promise.resolve();
  expect(resolved).toBe(false);

  dispatch(parent, "revision-next");
  await expect(admitted).resolves.toMatchObject({
    lifecycleId: 7,
    revision: "revision-next",
  });
});

test("standalone presentations do not require Studio admission", async () => {
  globalThis.history.replaceState({}, "", "/dashboard/");

  await expect(
    waitForReceiverAdmission(
      {
        lifecycleId: 1,
        runtime: "server",
        view: "dashboard",
        revision: () => "revision-current",
      },
      false,
    ),
  ).resolves.toBeUndefined();
});

test("document retirement releases a pending Studio admission", async () => {
  const parent = globalThis.window;
  vi.stubGlobal("parent", parent);
  const lifetime = new AbortController();
  const retirement = new PresentationDocumentRetiredError();
  const admitted = waitForReceiverAdmission(
    {
      lifecycleId: 7,
      runtime: "server",
      view: "dashboard",
      revision: () => "revision-current",
    },
    true,
    lifetime.signal,
  );

  lifetime.abort(retirement);

  await expect(admitted).rejects.toBe(retirement);
  dispatch(parent, "revision-current");
});
