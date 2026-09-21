import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  viewHistoryNavigationForUrl,
  viewNavigationForUrl,
} from "../src/document/view-navigation.ts";

const selection = (href: string, currentView = "novice", runtimeExplicit = false) =>
  viewNavigationForUrl({
    href,
    origin: "https://example.test",
    publicRootUrl: "/proxy/token/",
    documentRootUrl: "/proxy/token/",
    publicQuery: "",
    unframed: false,
    trustedRuntime: { id: "server", explicit: runtimeExplicit },
    views: ["novice", "intermediate", "expert"],
    currentView,
  });

const authoredRoot =
  "https://example.test/proxy/token/_marimo-studio/notebooks/YW5hbHlzaXMucHk/views/";
const authoredSelection = (path: string) =>
  viewNavigationForUrl({
    href: `${authoredRoot}${path}`,
    origin: "https://example.test",
    publicRootUrl: "/proxy/token/?file=analysis.py",
    documentRootUrl: new URL(authoredRoot).pathname,
    publicQuery: "?region=eu",
    unframed: false,
    trustedRuntime: { id: "server", explicit: false },
    views: ["novice", "expert"],
    currentView: "novice",
  });

const relativeSelection = (href: string) =>
  viewNavigationForUrl({
    href,
    origin: "https://example.test",
    publicRootUrl: "/proxy/token/?file=analysis.py",
    documentRootUrl: new URL(authoredRoot).pathname,
    publicQuery: "?region=eu",
    unframed: false,
    trustedRuntime: { id: "server", explicit: false },
    views: ["novice", "expert"],
    currentView: "novice",
  });

test("configured view URLs resolve beneath Marimo's base path and identify the current view", () => {
  const base = new URL("/proxy/token/", "https://example.test");

  assert.deepEqual(selection(new URL("./intermediate/", base).href), {
    view: "intermediate",
    current: false,
    documentUrl: "https://example.test/proxy/token/intermediate/",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/expert/"), {
    view: "expert",
    current: false,
    documentUrl: "https://example.test/proxy/token/expert/",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/novice/"), {
    view: "novice",
    current: true,
    documentUrl: "https://example.test/proxy/token/novice/",
  });
});

test("authored routes navigate through their public notebook URL", () => {
  const cases = [
    [
      "expert/",
      {
        view: "expert",
        current: false,
        documentUrl: "https://example.test/proxy/token/expert/?file=analysis.py&region=eu",
      },
    ],
    [
      "novice/#details",
      {
        view: "novice",
        current: true,
        documentUrl: "https://example.test/proxy/token/novice/?file=analysis.py&region=eu#details",
      },
    ],
    [
      "novice/?region=us",
      {
        view: "novice",
        current: true,
        documentUrl: "https://example.test/proxy/token/novice/?file=analysis.py&region=us",
      },
    ],
  ] as const;

  for (const [path, expected] of cases) {
    assert.deepEqual(authoredSelection(path), expected);
  }
});

test("relative authored links resolve from the current public view", () => {
  assert.deepEqual(relativeSelection("#details"), {
    view: "novice",
    current: true,
    documentUrl: "https://example.test/proxy/token/novice/?file=analysis.py&region=eu#details",
  });
  assert.deepEqual(relativeSelection("?region=us"), {
    view: "novice",
    current: true,
    documentUrl: "https://example.test/proxy/token/novice/?file=analysis.py&region=us",
  });
  assert.deepEqual(relativeSelection("../expert/"), {
    view: "expert",
    current: false,
    documentUrl: "https://example.test/proxy/token/expert/?file=analysis.py&region=eu",
  });
  assert.deepEqual(relativeSelection("../expert/index.html"), {
    view: "expert",
    current: false,
    documentUrl: "https://example.test/proxy/token/expert/?file=analysis.py&region=eu",
  });
  assert.equal(relativeSelection("./assets/report.csv"), undefined);
});

test("authored runtime and private transport state cannot replace trusted navigation", () => {
  assert.deepEqual(
    selection(
      "https://example.test/proxy/token/expert/?region=eu&runtime=wasm" +
        "&access_token=forged&file=forged.py&session_id=s_forged" +
        "&marimo_studio_client=forged&marimo_studio_lifecycle=99" +
        "&marimo_studio_resume=1",
    ),
    {
      view: "expert",
      current: false,
      documentUrl: "https://example.test/proxy/token/expert/?region=eu",
    },
  );
  assert.deepEqual(
    selection("https://example.test/proxy/token/expert/?region=eu&runtime=wasm", "novice", true),
    {
      view: "expert",
      current: false,
      documentUrl: "https://example.test/proxy/token/expert/?region=eu&runtime=server",
    },
  );
  assert.deepEqual(
    selection("https://example.test/proxy/token/expert/?region=eu", "novice", true),
    {
      view: "expert",
      current: false,
      documentUrl: "https://example.test/proxy/token/expert/?region=eu&runtime=server",
    },
  );
});

test("history navigation canonicalizes runtime before restore or query reload", () => {
  const historyNavigation = (href: string, mountedDocumentUrl: string, runtimeExplicit = false) =>
    viewHistoryNavigationForUrl({
      href,
      origin: "https://example.test",
      publicRootUrl: "/proxy/token/",
      documentRootUrl: "/proxy/token/",
      publicQuery: "?region=apac",
      unframed: false,
      trustedRuntime: { id: "server", explicit: runtimeExplicit },
      views: ["novice", "expert"],
      currentView: "novice",
      mountedDocumentUrl,
    });

  assert.deepEqual(
    historyNavigation(
      "https://example.test/proxy/token/expert/?region=apac&runtime=wasm",
      "https://example.test/_marimo-studio/presentation/revision/novice/?region=apac",
    ),
    {
      navigation: {
        view: "expert",
        current: false,
        documentUrl: "https://example.test/proxy/token/expert/?region=apac",
      },
      publicQueryChanged: false,
    },
  );
  assert.deepEqual(
    historyNavigation(
      "https://example.test/proxy/token/expert/?region=apac&runtime=wasm",
      "https://example.test/_marimo-studio/presentation/revision/novice/?region=emea",
      true,
    ),
    {
      navigation: {
        view: "expert",
        current: false,
        documentUrl: "https://example.test/proxy/token/expert/?region=apac&runtime=server",
      },
      publicQueryChanged: true,
    },
  );
});

test("view navigation leaves other links to the browser", () => {
  assert.deepEqual(selection("https://other.test/proxy/token/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/proxy/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/proxy/token/intermediate/?region=eu"), {
    view: "intermediate",
    current: false,
    documentUrl: "https://example.test/proxy/token/intermediate/?region=eu",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/intermediate/#results"), {
    view: "intermediate",
    current: false,
    documentUrl: "https://example.test/proxy/token/intermediate/#results",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/missing/"), undefined);
});

test("unframed navigation preserves delivery mode separately from notebook query", () => {
  for (const [href, view, region, hash] of [
    ["?region=us", "novice", "us", ""],
    ["#details", "novice", "eu", "#details"],
    ["../expert/", "expert", "eu", ""],
  ] as const) {
    const navigation = viewNavigationForUrl({
      href,
      origin: "https://example.test",
      publicRootUrl: "/proxy/?file=analysis.py",
      documentRootUrl: "/proxy/",
      publicQuery: "?region=eu",
      trustedRuntime: { id: "wasm", explicit: true },
      unframed: true,
      views: ["novice", "expert"],
      currentView: "novice",
    });
    assert.ok(navigation);
    const url = new URL(navigation.documentUrl);
    assert.equal(url.searchParams.get("marimo_studio_unframed"), "1");
    assert.equal(url.searchParams.get("file"), "analysis.py");
    assert.equal(url.searchParams.get("runtime"), "wasm");
    assert.equal(navigation.view, view);
    assert.equal(url.searchParams.get("region"), region);
    assert.equal(url.hash, hash);
  }
});

test("same-view navigation keeps its exact checkpoint and cross-view navigation clears it", () => {
  const options = {
    origin: "https://example.test",
    publicRootUrl: "/proxy/?file=book.py",
    documentRootUrl: "/proxy/",
    publicQuery: "?region=eu",
    unframed: true,
    trustedRuntime: { id: "wasm", explicit: true },
    views: ["novice", "expert"],
    currentView: "novice",
    exactRevision: "committed-revision",
  };
  const same = viewNavigationForUrl({ ...options, href: "?region=us#details" });
  const other = viewNavigationForUrl({
    ...options,
    href: "../expert/?marimo_studio_revision=forged",
  });
  assert.equal(
    new URL(same!.documentUrl).searchParams.get("marimo_studio_revision"),
    "committed-revision",
  );
  assert.equal(new URL(same!.documentUrl).searchParams.get("region"), "us");
  assert.equal(new URL(other!.documentUrl).searchParams.has("marimo_studio_revision"), false);
});

test("standalone links keep their admitted editor binding across views and ignore authored binding overrides", () => {
  const options = {
    origin: "https://example.test",
    publicRootUrl: "/proxy/?file=book.py",
    documentRootUrl: "/proxy/",
    publicQuery: "?region=eu",
    unframed: true,
    trustedRuntime: { id: "server", explicit: true },
    views: ["novice", "expert"],
    currentView: "novice",
    clientId: "current-client",
    supportUrl: "/support/novice?marimo_studio_editor_session=s_current",
  };
  for (const href of [
    "?region=us",
    "../expert/?marimo_studio_client=forged&marimo_studio_editor_session=s_forged",
  ]) {
    const navigation = viewNavigationForUrl({ ...options, href });
    const url = new URL(navigation!.documentUrl);
    assert.equal(url.searchParams.get("marimo_studio_client"), "current-client");
    assert.equal(url.searchParams.get("marimo_studio_editor_session"), "s_current");
  }
});
