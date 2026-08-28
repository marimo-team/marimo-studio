import { spawn } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";

import { cleanupNgaProviderEnvironment } from "./cleanup-nga-provider.mjs";
import { e2eNetwork } from "./network.mjs";
import {
  externalProviderNotebookPath,
  providerConfigDirectory,
  providerGalleryStaticDirectory,
  providerNotebookPath,
  providerStoryStaticDirectory,
  repositoryDirectory,
} from "./paths.mjs";
import { PreparationProcessOwner } from "./preparation-process.mjs";
import {
  clearNgaProviderGeneratedState,
  prepareNgaProviderWorkspace,
} from "./prepare-nga-provider.mjs";
import { stopProcessGroup } from "./process-group.mjs";
import { captureProcessOutput, stopNotebookProcess, waitForServer } from "./server-process.mjs";

const preparation = new PreparationProcessOwner();
const children = [];
const closures = [];
const shutdowns = [];
const outputs = new WeakMap();
let live;
let external;
let galleryStatic;
let storyStatic;
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

const stopServer = (child, port, serverUrl, signal, shutdown) => {
  if (!child) return;
  shutdowns.push(
    stopNotebookProcess(
      { child, output: outputs.get(child), port, serverUrl },
      { shutdown, signal },
    ).catch((error) => {
      console.error(error);
      exitCode = 1;
    }),
  );
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
  children.forEach((child) => {
    if (child === live) {
      stopServer(
        child,
        e2eNetwork.provider.live.port,
        e2eNetwork.provider.live.origin,
        signal,
        "run",
      );
    } else if (child === external) {
      stopServer(
        child,
        e2eNetwork.provider.external.port,
        e2eNetwork.provider.external.origin,
        signal,
        "run",
      );
    } else if (child === galleryStatic) {
      stopServer(
        child,
        e2eNetwork.provider.gallery.port,
        e2eNetwork.provider.gallery.origin,
        signal,
        "process",
      );
    } else if (child === storyStatic) {
      stopServer(
        child,
        e2eNetwork.provider.story.port,
        e2eNetwork.provider.story.origin,
        signal,
        "process",
      );
    } else {
      stopProcessGroup(child.pid, signal);
    }
  });
};

const track = (child) => {
  children.push(child);
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
  await prepareNgaProviderWorkspace();
  preparation.requireActive();
  await rm(providerConfigDirectory, { force: true, recursive: true });
  preparation.requireActive();
  await mkdir(providerConfigDirectory, { recursive: true });

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
  for (const [view, output] of [
    ["gallery", providerGalleryStaticDirectory],
    ["story", providerStoryStaticDirectory],
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
    ]);
  }
  preparation.requireActive();
  await clearNgaProviderGeneratedState();
};

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGHUP", () => stop("SIGTERM"));

try {
  await prepare();
  preparation.requireActive();

  galleryStatic = track(
    spawnServer(
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
  );
  preparation.requireActive();
  storyStatic = track(
    spawnServer(
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
  );
  preparation.requireActive();
  external = track(
    spawnServer([
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
  );

  await Promise.all([
    waitForServer(galleryStatic, e2eNetwork.provider.gallery.origin),
    waitForServer(storyStatic, e2eNetwork.provider.story.origin),
    waitForServer(external, e2eNetwork.provider.external.origin, {
      output: outputs.get(external),
    }),
  ]);
  preparation.requireActive();
  live = track(
    spawnServer([
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
  );
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
await cleanupNgaProviderEnvironment();
process.exitCode = exitCode;
