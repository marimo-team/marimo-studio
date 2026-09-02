import { fileURLToPath } from "node:url";

import { appDirectory } from "./paths.mjs";
import { PreparationCancelled, PreparationProcessOwner } from "./preparation-process.mjs";

const shardCount = 3;
const portStride = 100;
const playwrightCli = fileURLToPath(import.meta.resolve("@playwright/test/cli"));
const forwardedArgs = process.argv.slice(2);
if (forwardedArgs[0] === "--") forwardedArgs.shift();
const signalExitCodes = Object.freeze({
  SIGHUP: 129,
  SIGINT: 130,
  SIGTERM: 143,
});

const preparation = new PreparationProcessOwner();
let exitCode = 0;
let stopping = false;

const stop = (signal) => {
  if (stopping) return;
  stopping = true;
  exitCode = signalExitCodes[signal] ?? 1;
  void preparation.stop(signal).catch((error) => {
    console.error(error);
    exitCode = 1;
  });
};

const signals = ["SIGINT", "SIGTERM", "SIGHUP"];
const signalHandlers = new Map(signals.map((signal) => [signal, () => stop(signal)]));
for (const [signal, handler] of signalHandlers) {
  process.on(signal, handler);
}

try {
  await Promise.all(
    Array.from({ length: shardCount }, (_, index) => {
      const shard = index + 1;
      return preparation.run(
        `main browser shard ${shard}/${shardCount}`,
        process.execPath,
        [playwrightCli, "test", `--shard=${shard}/${shardCount}`, ...forwardedArgs],
        {
          cwd: appDirectory,
          env: {
            ...process.env,
            MARIMO_STUDIO_E2E_PORT_OFFSET: String(shard * portStride),
          },
          stdio: "inherit",
        },
      );
    }),
  );
} catch (error) {
  if (!(stopping && error instanceof PreparationCancelled)) {
    console.error(error);
  }
  if (!stopping) exitCode = 1;
} finally {
  try {
    await preparation.stop("SIGTERM");
  } catch (error) {
    console.error(error);
    exitCode = 1;
  }
  for (const [signal, handler] of signalHandlers) {
    process.off(signal, handler);
  }
}

process.exitCode = exitCode;
