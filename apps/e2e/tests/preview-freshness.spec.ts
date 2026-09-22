import {
  dashboardHtmlPath,
  expect,
  readWorkspaceFile,
  recoverRequestAbort,
  studioEntryUrl,
  studioOrigin,
  test,
  waitForPreview,
  writeWorkspaceFile,
} from "./fixture.ts";

test.use({ services: ["studio"] });

test("a standalone preview catches up when publication overtakes its event connection", async ({
  page,
  context,
  browserDiagnostics,
}) => {
  await page.goto(studioEntryUrl);
  const editorPreview = await waitForPreview(page);
  const source = await readWorkspaceFile(dashboardHtmlPath);
  const preview = await context.newPage();
  let releaseConnection = () => {};
  const connection = new Promise<void>((resolve) => {
    releaseConnection = resolve;
  });
  let observeConnection = (_url: string) => {};
  const connecting = new Promise<string>((resolve) => {
    observeConnection = resolve;
  });
  await preview.route("**/_marimo-studio/views/dashboard/dev/events*", async (route) => {
    observeConnection(route.request().url());
    await connection;
    await route.continue();
  });
  try {
    await preview.goto(`${studioOrigin()}/dashboard/?file=notebook.py&marimo_studio_unframed=1`);
    await expect(preview.getByRole("heading", { name: "Studio browser fixture" })).toBeVisible();
    await expect(preview.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    const eventsUrl = new URL(await connecting);
    const documentPath = eventsUrl.pathname.replace(
      /\/_marimo-studio\/views\/dashboard\/dev\/events$/,
      "/dashboard/",
    );
    const supersededDocument = browserDiagnostics.expectRequestAbort({
      origin: studioOrigin(),
      method: "GET",
      path: new RegExp(`^${RegExp.escape(documentPath)}$`),
      required: false,
    });
    const initialStream = browserDiagnostics.expectActiveRequestAbort({
      origin: studioOrigin(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/dev\/events$/,
      status: 200,
    });

    await writeWorkspaceFile(
      dashboardHtmlPath,
      source.replace("Studio browser fixture", "Published while preview disconnected"),
    );
    await expect(
      editorPreview.getByRole("heading", { name: "Published while preview disconnected" }),
    ).toBeVisible();
    releaseConnection();
    await expect(
      preview.getByRole("heading", { name: "Published while preview disconnected" }),
    ).toBeVisible();
    await expect(preview.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await recoverRequestAbort(initialStream);
    const nextStream = browserDiagnostics.expectActiveRequestAbort({
      origin: studioOrigin(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/dashboard\/dev\/events$/,
      status: 200,
    });

    await writeWorkspaceFile(
      dashboardHtmlPath,
      source.replace("Studio browser fixture", "Published after preview caught up"),
    );
    await expect(
      preview.getByRole("heading", { name: "Published after preview caught up" }),
    ).toBeVisible();
    await expect(preview.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await recoverRequestAbort(nextStream);
    await recoverRequestAbort(supersededDocument);
  } finally {
    releaseConnection();
    await preview.close();
  }
});
