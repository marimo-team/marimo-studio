import type { FrameLocator } from "@playwright/test";

import { PROXIED_RUN_TOKEN } from "../scripts/main-workspace.ts";
import { proxiedRunNotebookPath } from "../scripts/paths.ts";
import {
  expect,
  labeledSlider,
  presentationFrame,
  presentationMount,
  proxiedRunUrl,
  test,
  WASM_PREVIEW_TIMEOUT,
} from "./fixture.ts";

// The proxy publishes `marimo run --token-password` beneath a random
// /s/<id>/p/<id>/ prefix and strips it before forwarding. The browser fixture
// fails the test when any request leaves that prefix.
test.use({ services: ["proxiedRun"] });

// The first visit carries the access token. Studio removes it with a redirect
// that stays beneath the prefix.
const withToken = (url: string) =>
  `${url}${url.includes("?") ? "&" : "?"}access_token=${PROXIED_RUN_TOKEN}`;

const ready = async (view: FrameLocator) => {
  await expect(view.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
};

test("presents and links views beneath a stripped proxy prefix", async ({ page }) => {
  const view = presentationFrame(page);

  await page.goto(withToken(proxiedRunUrl()));
  await ready(view);

  await expect(page).toHaveURL(`${proxiedRunUrl()}dashboard/`);
  await expect(view.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    `${proxiedRunUrl()}favicon.ico`,
  );
  await labeledSlider(view.locator("body"), /^Proxied scale/).press("End");
  await expect(view.locator('[mo-value="metric"]')).toHaveText("63");

  await view.getByRole("link", { name: "Report" }).click();
  await expect(page).toHaveURL(`${proxiedRunUrl()}report/`);
  await ready(view);
  const report = view.getByRole("heading", { name: "Proxied report" });
  await expect(report).toBeVisible();
  // The authored stylesheet resolves against the artifact base beneath the prefix.
  await expect(report).toHaveCSS("color", "rgb(12, 34, 56)");
  await expect(view.getByRole("heading", { name: "Proxied total: 63" })).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(`${proxiedRunUrl()}dashboard/`);
  await ready(view);
  await expect(view.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
});

test("replays a preserved session after reload beneath a stripped proxy prefix", async ({
  page,
}) => {
  const view = presentationFrame(page);
  const sessionId = () =>
    view.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);

  await page.goto(withToken(`${proxiedRunUrl()}report/`));
  await ready(view);
  await expect(page).toHaveURL(`${proxiedRunUrl()}report/`);
  await expect(view.getByRole("heading", { name: "Proxied total: 42" })).toBeVisible();
  await page.goto(`${proxiedRunUrl()}dashboard/`);
  await ready(view);
  await labeledSlider(view.locator("body"), /^Proxied scale/).press("End");
  await expect(view.locator('[mo-value="metric"]')).toHaveText("63");
  const replayed = await sessionId();
  expect(replayed).toMatch(/^s_[\da-z]{6}$/);

  await page.reload();
  await ready(view);

  await expect(page).toHaveURL(`${proxiedRunUrl()}dashboard/`);
  expect(await sessionId()).toBe(replayed);
  await expect(view.locator('[mo-value="metric"]')).toHaveText("63");
});

test("runs the Browser runtime beneath a stripped proxy prefix", async ({ page }) => {
  const view = presentationFrame(page);

  await page.goto(withToken(`${proxiedRunUrl()}dashboard/?runtime=wasm`));
  await expect(view.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready", {
    timeout: WASM_PREVIEW_TIMEOUT,
  });

  await expect(page).toHaveURL(`${proxiedRunUrl()}dashboard/?runtime=wasm`);
  expect((await presentationMount(view.locator("html"))).runtime).toBe("wasm");
  await expect(view.locator('[mo-value="metric"]')).toHaveText("42", {
    timeout: WASM_PREVIEW_TIMEOUT,
  });
  await labeledSlider(view.locator("body"), /^Proxied scale/).press("Home");
  await expect(view.locator('[mo-value="metric"]')).toHaveText("21");
});

test("opens an exact preview URL beneath a stripped proxy prefix", async ({ page, studioCli }) => {
  await studioCli.buildWorkspaceView("dashboard", proxiedRunNotebookPath, "production");

  const url = await studioCli.previewView(
    proxiedRunNotebookPath,
    proxiedRunUrl(),
    "dashboard",
    "server",
    { exact: true, accessToken: PROXIED_RUN_TOKEN },
  );

  expect(url.startsWith(`${proxiedRunUrl()}dashboard/?`)).toBe(true);
  expect(new URL(url).searchParams.has("access_token")).toBe(false);
  const revision = new URL(url).searchParams.get("marimo_studio_revision");
  expect(revision).toMatch(/^[0-9a-f]{64}$/);
  const response = await page.goto(withToken(url));
  expect(response?.headers()["marimo-studio-revision"]).toBe(revision);
  await expect(page.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  await expect(page.locator("html")).toHaveAttribute("data-marimo-studio-revision", revision!);
  await expect(page.getByRole("heading", { name: "Proxied dashboard" })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(new URL(`${proxiedRunUrl()}dashboard/`).pathname);
});
