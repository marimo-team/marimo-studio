import type { SessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";

import { act, createElement, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  presentationRefreshUrl,
  presentationRenewalSupportUrl,
} from "../src/document/refresh-url.ts";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import {
  clearProjectionBindingStale,
  notifyProjectionResolutionStale,
  projectionBindingIsStale,
} from "../src/projections/staleness.ts";
import { toBrowserDiagnostics } from "../src/readiness-diagnostics.ts";
import { readiness } from "../src/readiness.ts";
import { renderedViewDiagnostics } from "../src/rendered-view-state.ts";
import {
  commitRuntimeConfig,
  getRuntimeConfig,
  getSupportUrl,
  setSupportUrl,
  subscribeRuntimeConfig,
} from "../src/runtime-config/index.ts";
import { useRuntimeProjectionConfig } from "../src/runtime/use-runtime-config.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

globalThis.__MARIMO_MOUNT_CONFIG__ = {
  supportUrl: "/support/old",
  version: "test-version",
  revision: "revision-old",
  runtime: "server",
  runtimeExplicit: false,
  replay: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.head.replaceChildren();
  document.body.replaceChildren();
});

test("runtime refresh obtains config through the same-session renewal authority", () => {
  expect(
    presentationRenewalSupportUrl(
      "http://studio.test/_marimo-studio/presentation/d.file.dashboard.s_abc123.signature/dashboard/",
      "http://studio.test/_marimo-studio/presentation/r.file.dashboard.s_abc123.p.revision.artifact.signature/_marimo-studio/views/dashboard?file=notebook.py",
    ),
  ).toBe(
    "http://studio.test/_marimo-studio/presentation/d.file.dashboard.s_abc123.signature/_marimo-studio/views/dashboard?file=notebook.py",
  );
});

test("opaque edit refreshes use the signed document route", () => {
  const href =
    "http://studio.test/dashboard/?file=notebook.py" +
    "&marimo_studio_client=client-123456789" +
    "&marimo_studio_lifecycle=7" +
    "#details";

  expect(
    presentationRefreshUrl(
      {
        view: "dashboard",
        presentationSessionId: "s_abc123",
        supportUrl:
          "/_marimo-studio/presentation/r.file.dashboard.s_abc123.revision.artifact.signature/" +
          "_marimo-studio/views/dashboard?marimo_studio_server=server-1",
      },
      href,
      "s_runtime",
      {
        clientId: "client-123456789",
        lifecycleId: 7,
        renewalToken: "d.file.dashboard.s_abc123.s_mount1.signature",
        runtime: "server",
        runtimeSessionId: "s_mount1",
      },
    ),
  ).toBe(
    "http://studio.test/_marimo-studio/presentation/d.file.dashboard.s_abc123.s_mount1.signature/dashboard/" +
      "?file=notebook.py&marimo_studio_client=client-123456789" +
      "&marimo_studio_lifecycle=7" +
      "&session_id=s_mount1&marimo_studio_server=server-1#details",
  );
});

test("WASM refresh strips caller native session state", () => {
  expect(
    presentationRefreshUrl(
      {
        view: "dashboard",
        presentationSessionId: "s_abc123",
        supportUrl:
          "/_marimo-studio/presentation/r.file.dashboard.s_abc123.p.revision.artifact.signature/" +
          "_marimo-studio/views/dashboard?marimo_studio_server=server-1",
      },
      "http://studio.test/dashboard/?file=notebook.py&session_id=s_forged",
      "s_forged",
      {
        renewalToken: "d.file.dashboard.s_abc123.s_wasm01.signature",
        runtime: "wasm",
      },
    ),
  ).toBe(
    "http://studio.test/_marimo-studio/presentation/" +
      "d.file.dashboard.s_abc123.s_wasm01.signature/dashboard/" +
      "?file=notebook.py&marimo_studio_server=server-1",
  );
});

test("a failed history push restores document, styles, runtime, and URL identity", async () => {
  const evaluate = XPathExpression.prototype.evaluate;
  vi.spyOn(XPathExpression.prototype, "evaluate").mockImplementation(function (
    this: XPathExpression,
    contextNode,
    type = XPathResult.ANY_TYPE,
    result,
  ) {
    return evaluate.call(this, contextNode, type, result);
  });
  Object.defineProperty(globalThis, "CSS", {
    configurable: true,
    value: { escape: (value: string) => value },
  });
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.head.innerHTML = "<style>body { color: red; }</style>";
  const previousStyle = document.head.querySelector("style");
  document.title = "Old title";
  document.body.innerHTML =
    '<main id="app-shell">Old shell<marimo-output id="retained" value="report">' +
    "<strong>Current report</strong></marimo-output></main>";
  const previousShell = document.querySelector("#app-shell");
  const previousHost = document.querySelector("marimo-output");
  const previousOutput = previousHost?.firstElementChild;
  setSupportUrl("/support/old");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  const previousUrl = globalThis.location.href;
  const previousHistoryLength = globalThis.history.length;
  const next = runtimeConfig({
    revision: "revision-new",
    projectionRevision: "b".repeat(64),
    supportUrl: "/support/new",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      let url: string;
      if (input instanceof Request) {
        url = input.url;
      } else if (input instanceof URL) {
        url = input.href;
      } else {
        url = input;
      }
      if (url.includes("/next/")) {
        return new Response(
          "<html><head><title>New title</title><style>body { color: blue; }</style></head>" +
            '<body><main id="app-shell">New shell' +
            '<marimo-output id="retained" value="report" aria-label="Incoming report">' +
            "</marimo-output></main></body></html>",
          {
            headers: {
              "Marimo-Studio-Revision": "revision-new",
              "Marimo-Studio-Support-Url": "/support/new",
            },
          },
        );
      }
      return Response.json(next);
    }),
  );
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");
  const pushState = vi.spyOn(globalThis.history, "pushState").mockImplementation(() => {
    throw new Error("history push failed");
  });
  const unsubscribe = subscribeRuntimeConfig(() => {
    if (getRuntimeConfig().revision === "revision-old") {
      throw new Error("rollback subscriber failed");
    }
  });

  await expect(
    adapter.replace("/next/", "/support/new", new AbortController().signal, vi.fn(), "push"),
  ).rejects.toThrow("Presentation commit and rollback failed");
  unsubscribe();

  expect(document.querySelector("#app-shell")).toBe(previousShell);
  expect(previousShell?.textContent).toBe("Old shellCurrent report");
  expect(document.querySelector("marimo-output")).toBe(previousHost);
  expect(previousHost?.firstElementChild).toBe(previousOutput);
  expect(previousHost?.hasAttribute("aria-label")).toBe(false);
  expect(document.head.querySelector("style[data-marimo-studio-page-style]")).toBe(previousStyle);
  expect(document.title).toBe("Old title");
  expect(getSupportUrl()).toBe("/support/old");
  expect(getRuntimeConfig().revision).toBe("revision-old");
  expect(globalThis.location.href).toBe(previousUrl);
  expect(globalThis.history.length).toBe(previousHistoryLength);
  expect(pushState).toHaveBeenCalledOnce();
});

test("an unchanged document revision commits refreshed runtime bindings", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = '<main id="app-shell">Current shell</main>';
  const runtimeRoot = document.createElement("div");
  document.body.append(runtimeRoot);
  setSupportUrl("/support/old");
  const previous = runtimeConfig({
    revision: "revision-old",
    projectionRevision: "a".repeat(64),
    runtimeBindings: { cellRefs: { "cell:v1:result": "old-cell-id" } },
  });
  commitRuntimeConfig(previous);
  const refreshed = runtimeConfig({
    revision: "revision-old",
    projectionRevision: "b".repeat(64),
    runtimeBindings: { cellRefs: { "cell:v1:result": "new-cell-id" } },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/old/config")) {
        return Response.json(refreshed);
      }
      return new Response('<html><body><main id="app-shell">Ignored</main></body></html>', {
        headers: { "Marimo-Studio-Revision": "revision-old" },
      });
    }),
  );
  const events: string[] = [];
  const Probe = () => {
    const revision = useRuntimeProjectionConfig().projectionRevision;
    useLayoutEffect(() => {
      events.push(`commit:${revision}`);
      return () => {
        events.push(`release:${revision}`);
      };
    }, [revision]);
    return null;
  };
  const root = createRoot(runtimeRoot);
  await act(async () => root.render(createElement(Probe)));
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");

  try {
    await act(async () => {
      await adapter.replace(adapter.url, "/support/old", new AbortController().signal, vi.fn());
      events.push("replace:resolved");
    });
  } finally {
    await act(async () => root.unmount());
  }

  expect(getRuntimeConfig().runtimeBindings.cellRefs["cell:v1:result"]).toBe("new-cell-id");
  expect(document.querySelector("#app-shell")?.textContent).toBe("Current shell");
  expect(events.slice(0, 4)).toEqual([
    `commit:${previous.projectionRevision}`,
    `release:${previous.projectionRevision}`,
    `commit:${refreshed.projectionRevision}`,
    "replace:resolved",
  ]);
});

test("runtime subscribers observe the committed document", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = '<main id="app-shell">Old shell</main>';
  setSupportUrl("/support/old");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  const next = runtimeConfig({
    revision: "revision-new",
    projectionRevision: "b".repeat(64),
    supportUrl: "/support/new",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/new/config")) {
        return Response.json(next);
      }
      return new Response('<html><body><main id="app-shell">New shell</main></body></html>', {
        headers: {
          "Marimo-Studio-Revision": "revision-new",
          "Marimo-Studio-Support-Url": "/support/new",
        },
      });
    }),
  );
  const observedShells: Array<string | null | undefined> = [];
  const unsubscribe = subscribeRuntimeConfig(() => {
    if (getRuntimeConfig().revision === "revision-new") {
      observedShells.push(document.querySelector("#app-shell")?.textContent);
    }
  });
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");

  try {
    await adapter.replace("/next/", "/support/new", new AbortController().signal, vi.fn());
  } finally {
    unsubscribe();
  }

  expect(observedShells).toEqual(["New shell"]);
});

test("projection owners commit before document replacement resolves", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = '<main id="app-shell">Old shell</main>';
  const runtimeRoot = document.createElement("div");
  document.body.append(runtimeRoot);
  setSupportUrl("/support/old");
  const previous = runtimeConfig({
    revision: "revision-old",
    projectionRevision: "a".repeat(64),
  });
  const next = runtimeConfig({
    revision: "revision-new",
    projectionRevision: "b".repeat(64),
    supportUrl: "/support/new",
  });
  commitRuntimeConfig(previous);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/new/config")) {
        return Response.json(next);
      }
      return new Response('<html><body><main id="app-shell">New shell</main></body></html>', {
        headers: {
          "Marimo-Studio-Revision": "revision-new",
          "Marimo-Studio-Support-Url": "/support/new",
        },
      });
    }),
  );
  const events: string[] = [];
  const Probe = () => {
    const revision = useRuntimeProjectionConfig().projectionRevision;
    useLayoutEffect(() => {
      events.push(`commit:${revision}`);
      return () => {
        events.push(`release:${revision}`);
      };
    }, [revision]);
    return null;
  };
  const root = createRoot(runtimeRoot);
  await act(async () => root.render(createElement(Probe)));
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");

  try {
    await act(async () => {
      await adapter.replace("/next/", "/support/new", new AbortController().signal, vi.fn());
      events.push("replace:resolved");
    });
  } finally {
    await act(async () => root.unmount());
  }

  expect(events.slice(0, 4)).toEqual([
    `commit:${previous.projectionRevision}`,
    `release:${previous.projectionRevision}`,
    `commit:${next.projectionRevision}`,
    "replace:resolved",
  ]);
});

test("same-revision subscriber failure restores config, support, URL, and history", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = '<main id="app-shell">Current shell</main>';
  setSupportUrl("/support/old");
  const previous = runtimeConfig({ revision: "revision-old", supportUrl: "/support/old" });
  const refreshed = runtimeConfig({ revision: "revision-old", supportUrl: "/support/new" });
  commitRuntimeConfig(previous);
  const previousUrl = globalThis.location.href;
  const previousHistoryLength = globalThis.history.length;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/config")) {
        return Response.json(refreshed);
      }
      return new Response('<html><body><main id="app-shell">Ignored</main></body></html>', {
        headers: {
          "Marimo-Studio-Revision": "revision-old",
          "Marimo-Studio-Support-Url": "/support/new",
        },
      });
    }),
  );
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");
  const unsubscribe = subscribeRuntimeConfig(() => {
    throw new Error("subscriber failed");
  });

  await expect(
    adapter.replace("/next/", "/support/new", new AbortController().signal, vi.fn(), "push"),
  ).rejects.toThrow("subscriber failed");
  unsubscribe();

  expect(getSupportUrl()).toBe("/support/old");
  expect(getRuntimeConfig()).toEqual(previous);
  expect(globalThis.location.href).toBe(previousUrl);
  expect(globalThis.history.length).toBe(previousHistoryLength);
  expect(document.querySelector("#app-shell")?.textContent).toBe("Current shell");
});

test("fragment scrolling cannot invalidate a committed same-revision navigation", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = `
    <main id="app-shell">
      Current shell
      <section id="details">Details</section>
    </main>
  `;
  setSupportUrl("/support/old");
  const refreshed = runtimeConfig({ revision: "revision-old", supportUrl: "/support/new" });
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old", supportUrl: "/support/old" }));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/config")) {
        return Response.json(refreshed);
      }
      return new Response('<html><body><main id="app-shell">Ignored</main></body></html>', {
        headers: {
          "Marimo-Studio-Revision": "revision-old",
          "Marimo-Studio-Support-Url": "/support/new",
        },
      });
    }),
  );
  const details = document.querySelector<HTMLElement>("#details")!;
  details.scrollIntoView = vi.fn(() => {
    throw new Error("scroll failed");
  });
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");

  await expect(
    adapter.replace(
      "/next/#details",
      "/support/new",
      new AbortController().signal,
      vi.fn(),
      "push",
    ),
  ).resolves.toMatchObject({ reloadDocument: false });

  expect(getSupportUrl()).toBe("/support/new");
  expect(getRuntimeConfig()).toEqual(refreshed);
  expect(globalThis.location.hash).toBe("#details");
  expect(details.scrollIntoView).toHaveBeenCalledOnce();
});

test("same-revision bindings remain stale until projection identity advances", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = '<main id="app-shell">Current shell</main>';
  setSupportUrl("/support/old");
  const projectionRevision = "a".repeat(64);
  commitRuntimeConfig(
    runtimeConfig({
      revision: "revision-old",
      projectionRevision,
      runtimeBindings: { cellRefs: { "cell:v1:result": "old-cell-id" } },
    }),
  );
  const refreshed = runtimeConfig({
    revision: "revision-old",
    projectionRevision,
    runtimeBindings: { cellRefs: { "cell:v1:result": "new-cell-id" } },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/old/config")) {
        return Response.json(refreshed);
      }
      return new Response('<html><body><main id="app-shell">Ignored</main></body></html>', {
        headers: { "Marimo-Studio-Revision": "revision-old" },
      });
    }),
  );
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");
  notifyProjectionResolutionStale(projectionRevision);

  await adapter.replace(adapter.url, "/support/old", new AbortController().signal, vi.fn());

  expect(getRuntimeConfig().runtimeBindings.cellRefs["cell:v1:result"]).toBe("new-cell-id");
  expect(projectionBindingIsStale(projectionRevision)).toBe(true);
  clearProjectionBindingStale(projectionRevision);
});

test("a superseded candidate revision is rejected before runtime commit", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML = '<main id="app-shell">Current shell</main>';
  setSupportUrl("/support/old");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  const candidate = runtimeConfig({
    revision: "revision-candidate",
    supportUrl: "/support/candidate",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/candidate/config")) {
        return Response.json(candidate);
      }
      return new Response(
        init?.method === "HEAD"
          ? null
          : '<html><body><main id="app-shell">Candidate shell</main></body></html>',
        {
          headers: {
            "Marimo-Studio-Revision":
              init?.method === "HEAD" ? "revision-current" : "revision-candidate",
            "Marimo-Studio-Support-Url": "/support/candidate",
          },
        },
      );
    }),
  );
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");

  await expect(
    adapter.replace("/next/", "/support/candidate", new AbortController().signal, vi.fn()),
  ).rejects.toMatchObject({
    code: "presentation-revision-mismatch",
    transient: true,
  });

  expect(getRuntimeConfig().revision).toBe("revision-old");
  expect(getSupportUrl()).toBe("/support/old");
  expect(document.querySelector("#app-shell")?.textContent).toBe("Current shell");
});

test("a structural shell edit reloads an unchanged authored script", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  const script = '<script type="module">document.querySelector("button")?.focus()</script>';
  document.head.innerHTML = script;
  document.body.innerHTML = '<main id="app-shell"><button id="run">Run</button></main>';
  setSupportUrl("/support/old");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  const next = runtimeConfig({ revision: "revision-new", supportUrl: "/support/new" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/new/config")) {
        return Response.json(next);
      }
      return new Response(
        `<html><head>${script}</head><body>` +
          '<main id="app-shell"><button id="save">Save</button></main></body></html>',
        {
          headers: {
            "Marimo-Studio-Revision": "revision-new",
            "Marimo-Studio-Support-Url": "/support/new",
          },
        },
      );
    }),
  );
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");

  const result = await adapter.replace(
    "/next/",
    "/support/new",
    new AbortController().signal,
    vi.fn(),
  );

  expect(result.reloadDocument).toBe(true);
  expect(document.querySelector("button")?.id).toBe("run");
  expect(getRuntimeConfig().revision).toBe("revision-old");
});

test("a stylesheet-only revision keeps the authored shell and rendered projection mounted", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.head.innerHTML =
    '<style>body { color: red; }</style><script type="module" src="app.js"></script>';
  document.body.innerHTML =
    '<main id="app-shell"><h1>Dashboard</h1><marimo-output value="report"></marimo-output></main>';
  setSupportUrl("/support/old");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");
  const shell = document.querySelector<HTMLElement>("#app-shell")!;
  const host = document.querySelector<HTMLElement>("marimo-output")!;
  const rendered = document.createElement("strong");
  rendered.textContent = "Rendered report";
  host.append(rendered);
  const next = runtimeConfig({
    revision: "revision-new",
    supportUrl: "/support/new",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/new/config")) {
        return Response.json(next);
      }
      return new Response(
        "<html><head><title>Dashboard</title><style>body { color: blue; }</style>" +
          '<script type="module" src="app.js"></script></head>' +
          '<body><main id="app-shell"><h1>Dashboard</h1>' +
          '<marimo-output value="report"></marimo-output></main></body></html>',
        {
          headers: {
            "Marimo-Studio-Revision": "revision-new",
            "Marimo-Studio-Support-Url": "/support/new",
          },
        },
      );
    }),
  );
  const preservation = vi.spyOn(projectionHosts, "stagePreservation");

  await adapter.replace("/next/", "/support/new", new AbortController().signal, vi.fn());

  expect(preservation).not.toHaveBeenCalled();
  expect(document.querySelector("#app-shell")).toBe(shell);
  expect(document.querySelector("marimo-output")).toBe(host);
  expect(document.querySelector("marimo-output > strong")).toBe(rendered);
  expect(getRuntimeConfig().revision).toBe("revision-new");
});

test("a scriptless structural edit morphs an unchanged projection topology", async () => {
  const { DocumentRevisionAdapter } = await import("../src/document/revision-document.ts");
  document.body.innerHTML =
    '<main id="app-shell"><h1>Before</h1>' +
    '<marimo-output id="summary" value="report" data-marimo-studio-preserve></marimo-output></main>';
  setSupportUrl("/support/old");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  const adapter = new DocumentRevisionAdapter("s_preview", "s_runtime");
  const shell = document.querySelector<HTMLElement>("#app-shell")!;
  const host = document.querySelector<HTMLElement>("marimo-output")!;
  const rendered = document.createElement("strong");
  rendered.textContent = "Rendered report";
  host.append(rendered);
  const next = runtimeConfig({ revision: "revision-new", supportUrl: "/support/new" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.includes("/support/new/config")) {
        return Response.json(next);
      }
      return new Response(
        "<html><head><title>Dashboard</title></head><body>" +
          '<main id="app-shell"><h1>After</h1>' +
          '<marimo-output id="summary" value="report" data-marimo-studio-preserve></marimo-output>' +
          "</main></body></html>",
        {
          headers: {
            "Marimo-Studio-Revision": "revision-new",
            "Marimo-Studio-Support-Url": "/support/new",
          },
        },
      );
    }),
  );

  const result = await adapter.replace(
    "/next/",
    "/support/new",
    new AbortController().signal,
    vi.fn(),
  );

  expect(result.reloadDocument).toBe(false);
  expect(document.querySelector("#app-shell")).toBe(shell);
  expect(document.querySelector("h1")?.textContent).toBe("After");
  expect(document.querySelector("marimo-output")).toBe(host);
  expect(host.firstChild).toBe(rendered);
});

test("failed document refresh preserves error context in browser diagnostics", async () => {
  const { createPresentationRevisions } = await import("../src/document/revision-runtime.ts");
  const { BrowserSessionReplay } = await import("../src/document/session-preservation.ts");
  document.body.innerHTML = '<main id="app-shell">Current report</main>';
  const retained = document.querySelector("#app-shell");
  commitRuntimeConfig(runtimeConfig({ revision: "revision-old" }));
  readiness.start();
  const details = { context: { input: "data/records.csv", state: "baseline" } };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        {
          error: "provider-input-invalid",
          message: "The provider could not read its input.",
          hint: "Correct the input path, then retry.",
          ...details,
        },
        { status: 409 },
      ),
    ),
  );
  // SAFETY: The fixture supplies a valid Marimo session ID to the branded API.
  const revisions = createPresentationRevisions(
    "s_abc123" as SessionId,
    "s_preview",
    new BrowserSessionReplay(),
  );
  try {
    await expect(revisions.transition("/next/", "/support/new")).rejects.toMatchObject({
      code: "provider-input-invalid",
      details,
    });

    expect(toBrowserDiagnostics(renderedViewDiagnostics())).toContainEqual({
      code: "provider-input-invalid",
      severity: "error",
      message: "The provider could not read its input.",
      hint: "Correct the input path, then retry.",
      view: "dashboard",
      scope: "presentation",
      details,
    });
    expect(document.querySelector("#app-shell")).toBe(retained);
  } finally {
    revisions.dispose();
  }
});
