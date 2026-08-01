import { parse } from "@std/toml";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

interface MarimoSource {
  path: string;
  commit: string;
}

interface HtmxSource {
  path: string;
  version: string;
}

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const cache = join(here, ".cache");
const marimoRepository = "https://github.com/marimo-team/marimo.git";
const decoder = new TextDecoder();

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

const assertMarimoCheckoutVersion = (
  actual: string,
  expected: string,
): void => {
  if (actual !== expected) {
    throw new Error(
      `The Marimo checkout is ${actual}, but uv.lock resolves ${expected}`,
    );
  }
};

const run = async (
  command: string,
  args: string[],
  cwd: string,
): Promise<void> => {
  const result = await new Deno.Command(command, {
    args,
    cwd,
    stdout: "inherit",
    stderr: "inherit",
  }).output();
  if (!result.success) {
    throw new Error(`${command} exited with status ${result.code}`);
  }
};

const capture = async (
  command: string,
  args: string[],
  cwd: string,
): Promise<string> => {
  const result = await new Deno.Command(command, { args, cwd }).output();
  if (!result.success) {
    const detail = decoder.decode(result.stderr).trim();
    throw new Error(
      `${command} exited with status ${result.code}${
        detail ? `: ${detail}` : ""
      }`,
    );
  }
  return decoder.decode(result.stdout).trim();
};

const assertCheckoutVersion = async (
  path: string,
  expected: string,
): Promise<void> => {
  const actual = marimoVersionFromCheckout(
    await Deno.readTextFile(join(path, "pyproject.toml")),
  );
  assertMarimoCheckoutVersion(actual, expected);
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

const resolveHtmx = async (): Promise<HtmxSource> => {
  const path = fileURLToPath(import.meta.resolve("htmx.org"));
  const manifest: unknown = JSON.parse(
    await Deno.readTextFile(join(dirname(path), "..", "package.json")),
  );
  if (!isRecord(manifest) || typeof manifest.version !== "string") {
    throw new Error("The resolved htmx.org package must declare a version");
  }
  return { path, version: manifest.version };
};

const build = async (): Promise<void> => {
  const marimoVersion = marimoVersionFromUvLock(
    await Deno.readTextFile(join(root, "uv.lock")),
  );
  const marimo = await prepareMarimo(marimoVersion);
  const htmx = await resolveHtmx();
  await run(
    "node",
    [join(here, "build-vite.mjs"), root, marimo.path, htmx.path],
    root,
  );

  const output = join(
    root,
    "src",
    "marimo_studio",
    "_static",
    "server-runtime",
  );
  await Deno.copyFile(
    join(here, "src", "studio.css"),
    join(output, "studio.css"),
  );
  const styleSource = join(here, "src", "studio", "styles");
  const styleOutput = join(output, "studio", "styles");
  await Deno.mkdir(styleOutput, { recursive: true });
  for await (const entry of Deno.readDir(styleSource)) {
    if (entry.isFile && entry.name.endsWith(".css")) {
      await Deno.copyFile(
        join(styleSource, entry.name),
        join(styleOutput, entry.name),
      );
    }
  }
  await Deno.writeTextFile(
    join(output, "build-meta.json"),
    JSON.stringify(
      {
        marimo: {
          repository: marimoRepository,
          version: marimoVersion,
          commit: marimo.commit,
        },
        htmx: {
          version: htmx.version,
        },
      },
      null,
      2,
    ) + "\n",
  );
};

if (import.meta.main) {
  await build();
}
