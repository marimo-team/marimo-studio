import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { readMarimoSourceSync } from "../scripts/metadata.mjs";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export const createMarimoViteIntegration = () => {
  const source = readMarimoSourceSync();
  const frontend = join(source.path, "frontend");
  const modules = join(frontend, "node_modules");
  const rtc = join(packageRoot, "src", "server-only-rtc.ts");
  const logger = join(packageRoot, "src", "runtime-logger.ts");

  return {
    aliases: [
      {
        find: "@/core/codemirror/rtc/extension",
        replacement: rtc,
      },
      {
        find: "@/utils/Logger",
        replacement: logger,
      },
      {
        find: /^@marimo-team\/frontend\/unstable_internal\/(.*)$/,
        replacement: `${join(frontend, "src")}/$1`,
      },
      {
        find: /^@\/(.*)$/,
        replacement: `${join(frontend, "src")}/$1`,
      },
      // Marimo's exported store, hooks, and providers must share these module
      // instances with the presentation runtime that consumes them.
      {
        find: "react-dom",
        replacement: join(modules, "react-dom"),
      },
      {
        find: "react",
        replacement: join(modules, "react"),
      },
      {
        find: "jotai",
        replacement: join(modules, "jotai"),
      },
      {
        find: "zod",
        replacement: join(modules, "zod"),
      },
    ],
    postcss: join(frontend, "postcss.config.cjs"),
    source,
  };
};
