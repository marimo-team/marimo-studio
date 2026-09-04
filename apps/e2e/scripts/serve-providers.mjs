import { spawn } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";

import { cleanupProviderEnvironment } from "./cleanup-provider-runtime.mjs";
import { e2eNetwork } from "./network.mjs";
import {
  externalProviderNotebookPath,
  providerConfigDirectory,
  providerGalleryStaticDirectory,
  providerNotebookPath,
  providerRevealStaticDirectory,
  providerStoryStaticDirectory,
  providerWebStaticDirectory,
  repositoryDirectory,
} from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";
import {
  clearProviderGeneratedState,
  prepareProviderWorkspace,
} from "./prepare-provider-runtime.mjs";
import { captureProcessOutput, stopNotebookProcess, waitForServer } from "./server-process.mjs";

const preparation = new PreparationProcessOwner();
const closures = [];
const servers = [];
const shutdowns = [];
const outputs = new WeakMap();
let external;
let galleryStatic;
let revealStatic;
let storyStatic;
let webStatic;
let stopping = false;
let exitCode = 0;

const spawnServer = (args, options = {}) => {
  const child = spawn("uv", args, {
    cwd: repositoryDirectory,
    detached: process.platform !== "win32",
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
      XDG_CONFIG_HOME: providerConfigDirectory,
    },
    stdio: options.stdio ?? ["ignore", "pipe", "pipe"],
  });
  if (child.stdout || child.stderr) {
    outputs.set(
      child,
      captureProcessOutput(child, { stdout: process.stdout, stderr: process.stderr }),
    );
  }
  return child;
};

const stop = (signal) => {
  if (stopping) return;
  stopping = true;
  shutdowns.push(
    preparation.stop(signal).catch((error) => {
      console.error(error);
      exitCode = 1;
    }),
  );
  for (const { shutdown, timeout, ...server } of servers) {
    shutdowns.push(
      stopNotebookProcess(server, { shutdown, signal, timeout }).catch((error) => {
        console.error(error);
        exitCode = 1;
      }),
    );
  }
};

const track = ({ child, ...server }) => {
  servers.push({
    child,
    ...server,
    output: () => outputs.get(child)?.() ?? "",
  });
  closures.push(
    new Promise((accept) => {
      child.on("error", (error) => {
        console.error(error);
        exitCode = 1;
        stop("SIGTERM");
      });
      child.on("exit", (code, signal) => {
        if (!stopping) {
          exitCode = code === 0 && !signal ? 1 : (code ?? 1);
          stop("SIGTERM");
        }
      });
      child.on("close", accept);
    }),
  );
  return child;
};

const run = async (label, args) => {
  const started = performance.now();
  try {
    await preparation.run(label, "uv", args, {
      cwd: repositoryDirectory,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: "inherit",
    });
  } finally {
    const seconds = ((performance.now() - started) / 1000).toFixed(2);
    console.log(`[provider-e2e] ${label}: ${seconds}s`);
  }
};

const prepare = async () => {
  preparation.requireActive();
  await prepareProviderWorkspace();
  preparation.requireActive();
  await rm(providerConfigDirectory, { force: true, recursive: true });
  preparation.requireActive();
  await mkdir(providerConfigDirectory, { recursive: true });

  for (const [view, starter] of [
    ["overview", "marimo-studio/vanilla:default"],
    ["gallery", "marimo-studio/react:default"],
    ["story", "marimo-studio/svelte:default"],
    ["slides", "marimo-studio/react:reveal"],
  ]) {
    await run(`create ${view} provider view`, [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo-studio",
      "view",
      "create",
      view,
      "--target",
      providerNotebookPath,
      "--starter",
      starter,
      "--json",
    ]);
  }
  await run("create external provider view", [
    "run",
    "--frozen",
    "--group",
    "e2e",
    "marimo-studio",
    "view",
    "create",
    "dashboard",
    "--target",
    externalProviderNotebookPath,
    "--starter",
    "marimo-studio-e2e-provider/report:default",
    "--json",
  ]);
  await run("create external web view", [
    "run",
    "--frozen",
    "--group",
    "e2e",
    "marimo-studio",
    "view",
    "create",
    "web",
    "--target",
    providerNotebookPath,
    "--starter",
    "marimo-studio-e2e-provider/web:default",
    "--json",
  ]);
  for (const [view, output] of [
    ["gallery", providerGalleryStaticDirectory],
    ["story", providerStoryStaticDirectory],
    ["web", providerWebStaticDirectory],
    ["slides", providerRevealStaticDirectory],
  ]) {
    preparation.requireActive();
    await run(`export ${view} production`, [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo-studio",
      "view",
      "export",
      view,
      "--target",
      providerNotebookPath,
      "--output",
      output,
      "--runtime",
      "wasm",
    ]);
  }
  preparation.requireActive();
  await clearProviderGeneratedState();
};

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGHUP", () => stop("SIGTERM"));

try {
  await prepare();
  preparation.requireActive();

  galleryStatic = track({
    child: spawnServer(
      [
        "run",
        "python",
        "-m",
        "http.server",
        String(e2eNetwork.provider.gallery.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        providerGalleryStaticDirectory,
      ],
      { stdio: "ignore" },
    ),
    port: e2eNetwork.provider.gallery.port,
    serverUrl: e2eNetwork.provider.gallery.origin,
    shutdown: "process",
  });
  preparation.requireActive();
  storyStatic = track({
    child: spawnServer(
      [
        "run",
        "python",
        "-m",
        "http.server",
        String(e2eNetwork.provider.story.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        providerStoryStaticDirectory,
      ],
      { stdio: "ignore" },
    ),
    port: e2eNetwork.provider.story.port,
    serverUrl: e2eNetwork.provider.story.origin,
    shutdown: "process",
  });
  preparation.requireActive();
  webStatic = track({
    child: spawnServer(
      [
        "run",
        "python",
        "-m",
        "http.server",
        String(e2eNetwork.provider.web.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        providerWebStaticDirectory,
      ],
      { stdio: "ignore" },
    ),
    port: e2eNetwork.provider.web.port,
    serverUrl: e2eNetwork.provider.web.origin,
    shutdown: "process",
  });
  preparation.requireActive();
  revealStatic = track({
    child: spawnServer(
      [
        "run",
        "python",
        "-m",
        "http.server",
        String(e2eNetwork.provider.reveal.port),
        "--bind",
        "127.0.0.1",
        "--directory",
        providerRevealStaticDirectory,
      ],
      { stdio: "ignore" },
    ),
    port: e2eNetwork.provider.reveal.port,
    serverUrl: e2eNetwork.provider.reveal.origin,
    shutdown: "process",
  });
  preparation.requireActive();
  external = track({
    child: spawnServer([
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo",
      "run",
      externalProviderNotebookPath,
      "--no-sandbox",
      "--headless",
      "--no-token",
      "--host",
      "127.0.0.1",
      "--port",
      String(e2eNetwork.provider.external.port),
    ]),
    port: e2eNetwork.provider.external.port,
    serverUrl: e2eNetwork.provider.external.origin,
    shutdown: "run",
  });

  await Promise.all([
    waitForServer(galleryStatic, e2eNetwork.provider.gallery.origin),
    waitForServer(storyStatic, e2eNetwork.provider.story.origin),
    waitForServer(webStatic, `${e2eNetwork.provider.web.origin}/src/index.html`),
    waitForServer(revealStatic, e2eNetwork.provider.reveal.origin),
    waitForServer(external, e2eNetwork.provider.external.origin, {
      output: outputs.get(external),
    }),
  ]);
  preparation.requireActive();
  track({
    child: spawnServer([
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo",
      "run",
      providerNotebookPath,
      "--no-sandbox",
      "--headless",
      "--no-token",
      "--host",
      "127.0.0.1",
      "--port",
      String(e2eNetwork.provider.live.port),
    ]),
    port: e2eNetwork.provider.live.port,
    serverUrl: e2eNetwork.provider.live.origin,
    shutdown: "run",
  });
  await Promise.all(closures);
} catch (error) {
  if (!stopping) {
    console.error(error);
    exitCode = 1;
    stop("SIGTERM");
  }
  await Promise.allSettled(closures);
}

await Promise.allSettled(shutdowns);
await cleanupProviderEnvironment();
process.exitCode = exitCode;
