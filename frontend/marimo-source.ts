import { parse } from "@std/toml";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { capture, run } from "./command.ts";

export interface MarimoSource {
  path: string;
  commit: string;
}

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const cache = join(here, ".cache");
export const marimoRepository = "https://github.com/marimo-team/marimo.git";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const marimoVersionFromUvLock = (source: string): string => {
  const lock = parse(source);
  const packages = isRecord(lock) ? lock.package : undefined;
  const marimo = Array.isArray(packages)
    ? packages.find((entry) => isRecord(entry) && entry.name === "marimo")
    : undefined;
  if (
    !isRecord(marimo) ||
    typeof marimo.version !== "string" ||
    !marimo.version
  ) {
    throw new Error("uv.lock must contain a versioned marimo package");
  }
  return marimo.version;
};

const marimoVersionFromCheckout = (source: string): string => {
  const document = parse(source);
  const project = isRecord(document) ? document.project : undefined;
  const version = isRecord(project) ? project.version : undefined;
  if (typeof version !== "string" || !version) {
    throw new Error("The Marimo checkout must declare project.version");
  }
  return version;
};

const checkoutVersion = async (path: string): Promise<string> => {
  return marimoVersionFromCheckout(
    await Deno.readTextFile(join(path, "pyproject.toml")),
  );
};

const assertCheckoutVersion = async (
  path: string,
  expected: string,
): Promise<void> => {
  const actual = await checkoutVersion(path);
  if (actual !== expected) {
    throw new Error(
      `The Marimo checkout is ${actual}, but uv.lock resolves ${expected}`,
    );
  }
};

export const prepareMarimo = async (
  version: string,
): Promise<MarimoSource> => {
  const configured = Deno.env.get("MARIMO_REPO");
  if (configured) {
    const path = resolve(configured);
    await assertCheckoutVersion(path, version);
    return {
      path,
      commit: await capture("git", ["rev-parse", "HEAD"], path),
    };
  }

  const checkout = join(cache, "marimo");
  try {
    await Deno.stat(join(checkout, ".git"));
  } catch {
    await Deno.mkdir(cache, { recursive: true });
    await run(
      "git",
      [
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        marimoRepository,
        checkout,
      ],
      root,
    );
  }

  const tag = `refs/tags/${version}`;
  await run(
    "git",
    ["fetch", "--force", "origin", `${tag}:${tag}`],
    checkout,
  );
  const commit = await capture(
    "git",
    ["rev-parse", `${tag}^{commit}`],
    checkout,
  );
  await run("git", ["checkout", "--detach", commit], checkout);
  await run("corepack", ["pnpm", "install", "--frozen-lockfile"], checkout);
  await run(
    "corepack",
    ["pnpm", "--dir", "packages/llm-info", "codegen"],
    checkout,
  );
  await assertCheckoutVersion(checkout, version);
  return { path: checkout, commit };
};
