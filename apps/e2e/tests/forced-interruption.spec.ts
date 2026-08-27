import { expect, test } from "@playwright/test";
import { existsSync } from "node:fs";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { z } from "zod";

import { fixtureDirectory, notebookProcessRegistryDirectory } from "../scripts/paths.mjs";
import { processGroupIsRunning } from "../scripts/process-group.mjs";
import {
  closeFailedNotebookServer,
  startNotebookServer,
  stopNotebookServer,
  waitForNotebookServer,
} from "./notebook-server.ts";

const bootstrapSchema = z.object({
  serverToken: z.string(),
  urls: z.object({ query: z.string() }),
});
const inventorySchema = z.object({ files: z.array(z.object({ sessionId: z.string() })) });

const availablePort = async (): Promise<number> => {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = z.object({ port: z.number().int().positive() }).parse(server.address());
  await new Promise<void>((resolveClose, reject) => {
    server.close((error) => (error === undefined ? resolveClose() : reject(error)));
  });
  return address.port;
};

const serverResponds = async (port: number): Promise<boolean> => {
  try {
    const response = await fetch(`http://127.0.0.1:${port}`);
    await response.body?.cancel();
    return response.ok;
  } catch {
    return false;
  }
};

test("forced runner shutdown drains every open native notebook session", async ({
  browser,
}, testInfo) => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-forced-interruption-"));
  const workspace = resolve(root, "workspace");
  await cp(fixtureDirectory, workspace, { recursive: true });
  const port = await availablePort();
  const server = startNotebookServer({
    authentication: ["--no-token"],
    command: "edit",
    port,
    target: resolve(workspace, "notebook.py"),
  });
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  let stopped = false;
  try {
    await waitForNotebookServer(server, `${server.serverUrl}/?file=notebook.py`);
    const pages = await Promise.all(contexts.map((context) => context.newPage()));
    await Promise.all(pages.map((page) => page.goto(`${server.serverUrl}/?file=notebook.py`)));
    const bootstrap = bootstrapSchema.parse(
      JSON.parse((await pages[0].locator("#marimo-studio-bootstrap").textContent()) ?? "null"),
    );
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
      .toBeGreaterThanOrEqual(2);

    await stopNotebookServer(server);
    stopped = true;

    expect(server.output()).not.toMatch(/resource_tracker|leaked semaphore/);
    expect(processGroupIsRunning(server.processGroupId)).toBe(false);
    expect(await serverResponds(port)).toBe(false);
    expect(existsSync(notebookProcessRegistryDirectory)).toBe(false);
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
    const cleanupFailure = !stopped ? await closeFailedNotebookServer(server) : undefined;
    if (cleanupFailure !== undefined) {
      await testInfo.attach("notebook-server-cleanup", {
        body: Buffer.from(cleanupFailure.message),
        contentType: "text/plain",
      });
    }
    expect(processGroupIsRunning(server.processGroupId)).toBe(false);
    expect(await serverResponds(port)).toBe(false);
    expect(existsSync(notebookProcessRegistryDirectory)).toBe(false);
    await rm(root, { force: true, recursive: true });
  }
});

test("run-mode shutdown drains an active kernel through process lifespan", async ({
  browser,
}, testInfo) => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-run-interruption-"));
  const workspace = resolve(root, "workspace");
  await cp(fixtureDirectory, workspace, { recursive: true });
  const notebook = resolve(workspace, "notebook.py");
  await writeFile(
    notebook,
    (await readFile(notebook, "utf8")).replace(
      "# preserve_session = false",
      "# preserve_session = true",
    ),
  );
  const port = await availablePort();
  const server = startNotebookServer({
    authentication: ["--token-password", "run-access-token"],
    command: "run",
    port,
    target: notebook,
  });
  const context = await browser.newContext();
  let stopped = false;
  try {
    const url = `${server.serverUrl}/dashboard/?access_token=run-access-token`;
    await waitForNotebookServer(server, url);
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

    await stopNotebookServer(server);
    stopped = true;

    expect(server.output()).not.toMatch(/resource_tracker|leaked semaphore/);
    expect(processGroupIsRunning(server.processGroupId)).toBe(false);
    expect(await serverResponds(port)).toBe(false);
    expect(existsSync(notebookProcessRegistryDirectory)).toBe(false);
  } finally {
    await context.close();
    const cleanupFailure = !stopped ? await closeFailedNotebookServer(server) : undefined;
    if (cleanupFailure !== undefined) {
      await testInfo.attach("notebook-server-cleanup", {
        body: Buffer.from(cleanupFailure.message),
        contentType: "text/plain",
      });
    }
    expect(processGroupIsRunning(server.processGroupId)).toBe(false);
    expect(await serverResponds(port)).toBe(false);
    expect(existsSync(notebookProcessRegistryDirectory)).toBe(false);
    await rm(root, { force: true, recursive: true });
  }
});
