import { expect } from "@playwright/test";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { z } from "zod";

import type { ServerHandle } from "../scripts/server-process.ts";

import { copyFixtureProviderPackage } from "../scripts/fixture-provider-package.ts";
import { e2eNetwork } from "../scripts/network.ts";
import { fixtureDirectory } from "../scripts/paths.ts";
import { portIsOpen, processGroupIsRunning } from "../scripts/process-group.ts";
import { readStudioBootstrap } from "./authoring-test-support.ts";
import { waitForViewPreview } from "./fixture.ts";
import { test } from "./network-fixture.ts";
import { closeFailedNotebookServer, startNotebookServer } from "./notebook-server.ts";

const expectProcessTreeRootStopped = (server: ServerHandle): void => {
  const groupRunning = processGroupIsRunning(server.processGroupId);
  if (groupRunning !== undefined) {
    expect(groupRunning).toBe(false);
  }
  expect(server.child.exitCode !== null || server.child.signalCode !== null).toBe(true);
};

const inventorySchema = z.object({ files: z.array(z.object({ sessionId: z.string() })) });
const MULTI_SESSION_SHUTDOWN_TIMEOUT = 15_000;
const MULTI_SESSION_PREVIEW_TIMEOUT = process.platform === "win32" ? 180_000 : 65_000;
const MULTI_SESSION_TEST_TIMEOUT = process.platform === "win32" ? 300_000 : 150_000;

const expectNotebookServerStopped = async (server: ServerHandle): Promise<void> => {
  expectProcessTreeRootStopped(server);
  expect(await portIsOpen(server.port)).toBe(false);
};

test("forced runner shutdown drains every open native notebook session", async ({
  browser,
}, testInfo) => {
  test.setTimeout(MULTI_SESSION_TEST_TIMEOUT);
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-forced-interruption-"));
  const workspace = resolve(root, "workspace");
  await cp(fixtureDirectory, workspace, { recursive: true });
  await cp(resolve(workspace, "notebook.py"), resolve(workspace, "peer.py"));
  await cp(
    resolve(workspace, "__marimo__/studio/notebook"),
    resolve(workspace, "__marimo__/studio/peer"),
    { recursive: true },
  );
  await copyFixtureProviderPackage(workspace);
  const endpoint = e2eNetwork.main.forcedInterruption;
  const server = startNotebookServer({
    authentication: ["--no-token"],
    command: "edit",
    endpoint,
    target: workspace,
  });
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  let stopped = false;
  try {
    await server.waitUntilReady(`${server.serverUrl}/?file=notebook.py`);
    const pages = await Promise.all(contexts.map((context) => context.newPage()));
    for (const [index, page] of pages.entries()) {
      const filename = index === 0 ? "notebook.py" : "peer.py";
      await page.goto(`${server.serverUrl}/?file=${filename}`, {
        timeout: 60_000,
        waitUntil: "domcontentloaded",
      });
      await waitForViewPreview(page, "dashboard", "server", MULTI_SESSION_PREVIEW_TIMEOUT);
    }
    const bootstrap = await readStudioBootstrap(pages[0]);
    const query = new URL(bootstrap.urls.query, server.serverUrl);
    const apiRoot = `${query.origin}${query.pathname.replace(/\/_marimo-studio\/query$/, "/api/home")}`;
    await expect
      .poll(async () => {
        const response = await pages[0].request.post(`${apiRoot}/running_notebooks`, {
          headers: { "Marimo-Server-Token": bootstrap.serverToken },
        });
        if (!response.ok()) return 0;
        return inventorySchema.parse(await response.json()).files.length;
      })
      .toBe(2);

    await server.close({ timeout: MULTI_SESSION_SHUTDOWN_TIMEOUT });
    await expectNotebookServerStopped(server);
    stopped = true;
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    const cleanupFailure = !stopped
      ? await closeFailedNotebookServer(server, { timeout: MULTI_SESSION_SHUTDOWN_TIMEOUT })
      : undefined;
    if (cleanupFailure !== undefined) {
      await testInfo.attach("notebook-server-cleanup", {
        body: Buffer.from(cleanupFailure.message),
        contentType: "text/plain",
      });
    }
    await expectNotebookServerStopped(server);
    await rm(root, { force: true, recursive: true });
  }
});

test("run-mode shutdown drains an active kernel through process lifespan", async ({
  browser,
}, testInfo) => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-run-interruption-"));
  const workspace = resolve(root, "workspace");
  await cp(fixtureDirectory, workspace, { recursive: true });
  await copyFixtureProviderPackage(workspace);
  const notebook = resolve(workspace, "notebook.py");
  await writeFile(
    notebook,
    (await readFile(notebook, "utf8")).replace(
      "# preserve_session = false",
      "# preserve_session = true",
    ),
  );
  const endpoint = e2eNetwork.main.runInterruption;
  const server = startNotebookServer({
    authentication: ["--token-password", "run-access-token"],
    command: "run",
    endpoint,
    target: notebook,
  });
  const context = await browser.newContext();
  let stopped = false;
  try {
    const url = `${server.serverUrl}/dashboard/?access_token=run-access-token`;
    await server.waitUntilReady(url);
    const page = await context.newPage();
    await page.goto(url);
    const presentation = page.frameLocator("iframe#marimo-studio-presentation");
    await expect(presentation.locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
      {
        timeout: 60_000,
      },
    );
    await expect(presentation.locator('[mo-value="metric"]')).toHaveText("42", {
      timeout: 60_000,
    });

    await server.close();
    await expectNotebookServerStopped(server);
    stopped = true;
  } finally {
    await context.close();
    const cleanupFailure = !stopped ? await closeFailedNotebookServer(server) : undefined;
    if (cleanupFailure !== undefined) {
      await testInfo.attach("notebook-server-cleanup", {
        body: Buffer.from(cleanupFailure.message),
        contentType: "text/plain",
      });
    }
    await expectNotebookServerStopped(server);
    await rm(root, { force: true, recursive: true });
  }
});
