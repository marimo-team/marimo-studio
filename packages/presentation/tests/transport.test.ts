import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { createServerTransportURL } from "../src/runtime/transport.ts";

const urls = () => [
  new URL("ws://example.test/base/ws?session_id=session&runtime=wasm&file=wrong.py"),
  new URL("https://example.test/base/sse?session_id=session&runtime=wasm&file=wrong.py"),
];
const unowned = { replay: false } as const;
const owned = {
  clientId: "client-123456789",
  lifecycleId: 7,
  replay: false,
} as const;

test("edit previews mark kernel transports as a kiosk consumer", () => {
  const configure = createServerTransportURL(
    true,
    undefined,
    "server-instance",
    "s_view01",
    undefined,
    unowned,
  );

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("session_id"), "s_view01");
    assert.deepEqual(url.searchParams.get("kiosk"), "true");
    assert.deepEqual(url.searchParams.get("marimo_studio_server"), "server-instance");
    assert.deepEqual(url.searchParams.has("runtime"), false);
    assert.deepEqual(url.searchParams.has("file"), false);
  }
});

test("run views retain public query while stripping private transport state", () => {
  const [ws, sse] = urls().map(
    createServerTransportURL(
      false,
      undefined,
      "server-instance",
      "s_view01",
      "?region=emea&access_token=secret&marimo_studio_client=forged-client" +
        "&marimo_studio_lifecycle=7&runtime=wasm&session_id=s_forged" +
        "&marimo_studio_resume=1",
      { replay: true },
    ),
  );

  assert.deepEqual(
    ws?.toString(),
    "ws://example.test/base/ws?region=emea&session_id=s_view01&marimo_studio_server=server-instance&marimo_studio_resume=1",
  );
  assert.deepEqual(
    sse?.toString(),
    "https://example.test/base/sse?region=emea&session_id=s_view01&marimo_studio_server=server-instance&marimo_studio_resume=1",
  );
});

test("directory views select their notebook on kernel transports", () => {
  const configure = createServerTransportURL(
    false,
    "nested/notebook.py",
    "server-instance",
    "s_view01",
    undefined,
    unowned,
  );

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("file"), "nested/notebook.py");
    assert.deepEqual(url.searchParams.has("runtime"), false);
  }
});

test("kernel transports carry public query and the exact Studio client owner", () => {
  const configure = createServerTransportURL(
    true,
    "notebook.py",
    "server-instance",
    "s_view01",
    "?region=emea&region=apac&access_token=secret&file=forged.py" +
      "&marimo_studio_client=client-123456789&marimo_studio_lifecycle=7" +
      "&marimo_studio_server=forged-server&runtime=wasm&session_id=s_forged",
    owned,
  );

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.getAll("region"), ["emea", "apac"]);
    assert.deepEqual(url.searchParams.get("file"), "notebook.py");
    assert.deepEqual(url.searchParams.get("marimo_studio_client"), "client-123456789");
    assert.deepEqual(url.searchParams.get("marimo_studio_server"), "server-instance");
    assert.deepEqual(url.searchParams.get("session_id"), "s_view01");
    assert.deepEqual(url.searchParams.get("kiosk"), "true");
    assert.deepEqual(url.searchParams.has("access_token"), false);
    assert.deepEqual(url.searchParams.get("marimo_studio_lifecycle"), "7");
    assert.deepEqual(url.searchParams.has("runtime"), false);
  }
});

test("popout transports ignore a source client without mount ownership", () => {
  const configure = createServerTransportURL(
    true,
    "notebook.py",
    "server-instance",
    "s_view01",
    "?region=apac&marimo_studio_client=client-123456789",
    unowned,
  );

  for (const url of urls().map(configure)) {
    assert.deepEqual(url.searchParams.get("region"), "apac");
    assert.deepEqual(url.searchParams.has("marimo_studio_client"), false);
    assert.deepEqual(url.searchParams.has("marimo_studio_lifecycle"), false);
  }
});

test("run transports reject a noncanonical replay marker", () => {
  const [url] = urls().map(
    createServerTransportURL(
      false,
      undefined,
      "server-instance",
      "s_view01",
      "?marimo_studio_resume=true",
      unowned,
    ),
  );

  assert.equal(url?.searchParams.has("marimo_studio_resume"), false);
});
