import {
  dashboardHtmlPath,
  dashboardManifestPath,
  expect,
  presentationFrame,
  previewFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  recoverResponseTransition,
  studioEntryUrl,
  studioOrigin,
  test,
  waitForPreview,
  writeDashboardSource,
  writeWorkspaceFile,
} from "./fixture.ts";

test("keeps standalone navigation inside server-authored route authority", async ({ page }) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const opened = page.context().waitForEvent("page");
  await page.getByLabel("Open preview in a new tab").click();
  const popout = await opened;
  await popout.waitForLoadState("domcontentloaded");
  const presentation = presentationFrame(popout);
  await expect(presentation.locator("html")).toBeAttached();
  expect(await popout.evaluate(() => globalThis.opener)).toBeNull();

  const navigate = (view: string, query: string, hash: string) =>
    presentation.locator("html").evaluate(
      (_html, request) => {
        parent.postMessage(
          {
            type: "marimo-studio:navigate-view",
            runtime: "server",
            lifecycleId: 1,
            ...request,
          },
          "*",
        );
      },
      { view, query, hash },
    );

  try {
    const original = popout.url();
    const unknownNavigation = popout
      .waitForURL((url) => url.href !== original, { timeout: 500 })
      .then(
        () => true,
        () => false,
      );
    await navigate("forged-view", "?region=forged&file=forged.py", "#forged");
    expect(await unknownNavigation).toBe(false);

    const privateQuery = new URLSearchParams({
      region: "apac",
      file: "forged.py",
      access_token: "forged",
      refresh_token: "forged",
      session_id: "s_forged",
      runtime: "wasm",
      kiosk: "true",
      marimo_studio_client: "forged",
      marimo_studio_connection: "99",
      marimo_studio_events: "untrusted",
      marimo_studio_lifecycle: "99",
      marimo_studio_query_operation: "forged",
      marimo_studio_resume: "forged",
      marimo_studio_server: "forged",
      marimo_studio_view: "forged",
    });
    const navigated = popout.waitForURL(
      (url) => url.pathname.endsWith("/dashboard/") && url.searchParams.get("region") === "apac",
    );
    await navigate("dashboard", `?${privateQuery}`, "#proof");
    await navigated;

    const target = new URL(popout.url());
    expect(target.pathname).toBe("/dashboard/");
    expect(Array.from(target.searchParams.keys()).sort()).toEqual(["file", "region"]);
    expect(target.searchParams.get("file")).toBe("notebook.py");
    expect(target.searchParams.get("region")).toBe("apac");
    expect(target.searchParams.get("runtime")).toBeNull();
    expect(
      await presentation.locator("html").evaluate(() => globalThis.__MARIMO_MOUNT_CONFIG__.runtime),
    ).toBe("server");
    expect(target.hash).toBe("#proof");
  } finally {
    await popout.close();
  }
});

test("rejects an untrusted authored workspace stream before client state changes", async ({
  browserDiagnostics,
  page,
}) => {
  const refused = browserDiagnostics.expectConsole({
    type: "error",
    text: /\/_marimo-studio\/dev\/events.*blocked by CORS policy/,
  });
  const closed = browserDiagnostics.expectRequestFailure({
    origin: studioOrigin,
    path: /^\/_marimo-studio\/dev\/events$/,
    method: "GET",
    errorText: "net::ERR_FAILED",
  });
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const source = await readWorkspaceFile(dashboardHtmlPath);

  const target = await preview.locator("html").evaluate(() => {
    const current = new URL(globalThis.location.href);
    const target = new URL("/_marimo-studio/dev/events", current);
    for (const key of ["file", "marimo_studio_client", "marimo_studio_server"]) {
      const value = current.searchParams.get(key);
      if (value !== null) target.searchParams.set(key, value);
    }
    target.searchParams.set("marimo_studio_connection", String(Number.MAX_SAFE_INTEGER));
    target.searchParams.set("marimo_studio_view", "dashboard");
    return target.href;
  });
  const denied = await page.request.get(target);
  expect(denied.status()).toBe(403);
  expect(await denied.json()).toMatchObject({ error: "workspace-events-forbidden" });

  await preview.locator("html").evaluate(async (_html, eventsUrl) => {
    await new Promise<void>((resolve, reject) => {
      const untrusted = new EventSource(eventsUrl);
      const timeout = globalThis.setTimeout(() => {
        untrusted.close();
        reject(new Error("The untrusted workspace stream did not settle"));
      }, 5_000);
      untrusted.onopen = () => {
        globalThis.clearTimeout(timeout);
        untrusted.close();
        reject(new Error("The untrusted workspace stream opened"));
      };
      untrusted.onerror = () => {
        globalThis.clearTimeout(timeout);
        untrusted.close();
        resolve();
      };
    });
  }, target);

  await writeDashboardSource(
    page,
    source.replace(
      "</main>",
      '<output id="workspace-events-capability-proof">stream retained</output></main>',
    ),
  );
  const refreshed = await waitForPreview(page);
  await expect(refreshed.locator("#workspace-events-capability-proof")).toHaveText(
    "stream retained",
    { timeout: 65_000 },
  );
  await expect(page.getByLabel("Switch page")).toContainText("dashboard");
  refused.recovered();
  closed.recovered();
});

test("keeps authored scripts inside presentation authority", async ({
  browserDiagnostics,
  page,
}) => {
  const denied = browserDiagnostics.expectResponse({
    status: 403,
    path: /\/_marimo-studio\/presentation\/[^/]+\/(?:_marimo-studio\/views(?:\/.*)?|api\/kernel\/run)$/,
    count: 5,
  });
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const source = await readWorkspaceFile(dashboardHtmlPath);
  const mountAttack = String.raw`<script>
    try {
      globalThis.__MARIMO_MOUNT_CONFIG__ = {
        ...globalThis.__MARIMO_MOUNT_CONFIG__,
        runtime: "wasm",
        runtimeExplicit: true,
        replay: true,
        clientId: "forged-client-id-0000",
        lifecycleId: 99,
        runtimeSessionId: "s_forged",
        sessionId: "s_forged",
        supportUrl: "/forged",
      };
    } catch {}
    try {
      const forged = new URL(location.href);
      forged.search = new URLSearchParams({
        file: "forged.py",
        runtime: "wasm",
        session_id: "s_forged",
        marimo_studio_client: "forged-client-id-0000",
        marimo_studio_lifecycle: "99",
        marimo_studio_resume: "1",
      });
      history.replaceState(null, "", forged);
    } catch {}
  </script>`;
  const probe = String.raw`<script type="module">
    let parentReadable = false;
    try {
      parentReadable = Boolean(parent.document.querySelector("#marimo-studio-host"));
    } catch {}
    const support = new URL(globalThis.__MARIMO_MOUNT_CONFIG__.supportUrl, location.href);
    const marker = "/_marimo-studio/views/";
    const boundary = support.pathname.indexOf(marker);
    if (boundary < 0) throw new Error("Presentation support URL is outside its capability");
    const capability = new URL(support.pathname.slice(0, boundary + 1), location.origin);
    const request = (path, method = "GET", headers = {}) => {
      const target = new URL(path, capability);
      for (const [key, value] of support.searchParams) target.searchParams.set(key, value);
      return fetch(target, { headers, method }).then((response) => response.status);
    };
    const sessionId = globalThis.__MARIMO_MOUNT_CONFIG__.sessionId;
    if (!sessionId) throw new Error("Presentation session is unavailable");
    const [config, source, crossView, create, remove, execute] = await Promise.all([
      request("_marimo-studio/views/dashboard/config", "GET", {
        "Marimo-Studio-Preview-Session-Id": sessionId,
      }),
      request("_marimo-studio/views/dashboard/source/index.html"),
      request("_marimo-studio/views/executive/config"),
      request("_marimo-studio/views", "POST"),
      request("_marimo-studio/views/executive", "DELETE"),
      request("api/kernel/run", "POST"),
    ]);
    const result = document.createElement("output");
    result.id = "presentation-authority-result";
    result.textContent = JSON.stringify({
      parentReadable,
      config,
      source,
      crossView,
      create,
      remove,
      execute,
    });
    document.body.append(result);
  </script>`;
  const configured = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname.includes("/_marimo-studio/views/dashboard/config") &&
      url.searchParams.has("runtime")
    );
  });
  const connected = page.waitForEvent("websocket", {
    predicate: (socket) => {
      const url = new URL(socket.url());
      return url.pathname.includes("/_marimo-studio/presentation/") && url.pathname.endsWith("/ws");
    },
  });
  await writeDashboardSource(
    page,
    source.replace("</head>", `${mountAttack}</head>`).replace("</body>", `${probe}</body>`),
  );
  const configuredRequest = await configured;
  expect(new URL(configuredRequest.url()).searchParams.get("runtime")).toBe("server");

  await expect(preview.locator("#presentation-authority-result")).toHaveText(
    JSON.stringify({
      parentReadable: false,
      config: 200,
      source: 403,
      crossView: 403,
      create: 403,
      remove: 403,
      execute: 403,
    }),
  );
  await expect(preview.locator('strong[mo-value="metric"]')).toHaveText("42");
  const trusted = await preview.locator("html").evaluate(() => ({
    descriptor: (() => {
      const descriptor = Object.getOwnPropertyDescriptor(globalThis, "__MARIMO_MOUNT_CONFIG__");
      return {
        configurable: descriptor?.configurable,
        writable: "writable" in (descriptor ?? {}) ? descriptor?.writable : undefined,
      };
    })(),
    href: location.href,
    nativeSessionId: globalThis.__MARIMO_STUDIO_SESSION_ID__,
    mount: {
      clientId: globalThis.__MARIMO_MOUNT_CONFIG__.clientId,
      lifecycleId: globalThis.__MARIMO_MOUNT_CONFIG__.lifecycleId,
      replay: globalThis.__MARIMO_MOUNT_CONFIG__.replay,
      runtime: globalThis.__MARIMO_MOUNT_CONFIG__.runtime,
      runtimeExplicit: globalThis.__MARIMO_MOUNT_CONFIG__.runtimeExplicit,
      runtimeSessionId: globalThis.__MARIMO_MOUNT_CONFIG__.runtimeSessionId,
      sessionId: globalThis.__MARIMO_MOUNT_CONFIG__.sessionId,
      supportUrl: globalThis.__MARIMO_MOUNT_CONFIG__.supportUrl,
    },
  }));
  expect(trusted.mount).toMatchObject({
    clientId: expect.stringMatching(/^[A-Za-z0-9_-]{16,128}$/),
    lifecycleId: expect.any(Number),
    replay: false,
    runtime: "server",
    runtimeExplicit: false,
    runtimeSessionId: expect.stringMatching(/^s_[a-z0-9]{6}$/),
    sessionId: expect.stringMatching(/^s_[a-z0-9]+$/),
  });
  expect(trusted.nativeSessionId).toBe(trusted.mount.runtimeSessionId);
  expect(trusted.mount.supportUrl).toContain("/_marimo-studio/views/dashboard");
  expect(trusted.descriptor).toEqual({ configurable: false, writable: false });
  expect(new URL(trusted.href).searchParams.get("runtime")).toBeNull();
  const configUrl = new URL(configuredRequest.url());
  expect(configUrl.searchParams.get("marimo_studio_client")).toBe(trusted.mount.clientId);
  expect(configuredRequest.headers()["marimo-studio-preview-session-id"]).toBe(
    trusted.mount.sessionId,
  );
  expect(configuredRequest.headers()["marimo-session-id"]).toBe(trusted.mount.runtimeSessionId);
  const socketUrl = new URL((await connected).url());
  expect(socketUrl.searchParams.get("marimo_studio_client")).toBe(trusted.mount.clientId);
  expect(socketUrl.searchParams.get("marimo_studio_lifecycle")).toBe(
    String(trusted.mount.lifecycleId),
  );
  expect(socketUrl.searchParams.get("session_id")).toBe(trusted.mount.sessionId);
  denied.recovered();
});

test("repairs an opaque preview through its scoped event stream", async ({
  browserDiagnostics,
  page,
}) => {
  const failedDocument = browserDiagnostics.expectResponse({
    status: 500,
    path: /\/dashboard\/$/,
  });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const supersededDocument = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "GET",
    path: /^\/(?:_marimo-studio\/presentation\/[^/]+\/)?dashboard\/$/,
    count: 1,
    required: false,
  });
  const closedRepairStream = browserDiagnostics.expectRequestAbort({
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/dev\/events$/,
    count: 1,
    status: 200,
  });
  const manifest = await readWorkspaceFile(dashboardManifestPath);
  const projectRepair = browserDiagnostics.expectResponseTransition(page, {
    origin: studioOrigin,
    method: "GET",
    path: /^\/_marimo-studio\/views\/dashboard\/project$/,
    failureStatus: 500,
    failureError: "configuration-error",
    successStatus: 200,
  });

  try {
    await writeWorkspaceFile(dashboardManifestPath, "this is not valid TOML =");
    const invalidProject = await page.request.get(
      "/_marimo-studio/views/dashboard/project?file=notebook.py",
    );
    expect(invalidProject.status()).toBe(500);
    expect(await invalidProject.json()).toMatchObject({ error: "configuration-error" });
    await expect
      .poll(async () => {
        const response = await page.request.get(
          "/_marimo-studio/views/dashboard/config?file=notebook.py",
        );
        return response.status();
      })
      .toBe(500);
    const scopedEvents = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        response.status() === 200 &&
        /\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/dev\/events$/.test(url.pathname)
      );
    });
    const frame = page.locator('iframe[data-preview-runtime-frame="server"]');
    await frame.evaluate((element: HTMLIFrameElement) => {
      element.setAttribute("src", element.src);
    });
    await expect(
      previewFrame(page).getByRole("heading", { name: "View needs repair" }),
    ).toBeVisible();
    await scopedEvents;

    projectRepair.seal();
    await writeWorkspaceFile(dashboardManifestPath, manifest);
    await waitForPreview(page);
    await expect(
      previewFrame(page).getByRole("heading", { name: "Studio browser fixture" }),
    ).toBeVisible();
    const repairedProject = await page.request.get(
      "/_marimo-studio/views/dashboard/project?file=notebook.py",
    );
    expect(repairedProject.status()).toBe(200);
    failedDocument.recovered();
    await recoverResponseTransition(projectRepair);
    await recoverRequestAbort(supersededDocument);
    await recoverRequestAbort(closedRepairStream);
  } finally {
    await writeWorkspaceFile(dashboardManifestPath, manifest);
  }
});
