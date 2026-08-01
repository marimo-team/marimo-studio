import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { marimoVersionFromUvLock, prepareMarimo } from "./marimo-source.ts";
import {
  resolveOwnedDependency,
  resolveProjectDependency,
} from "./upstream-dependency.ts";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

const typecheck = async (): Promise<void> => {
  const version = marimoVersionFromUvLock(
    await Deno.readTextFile(join(root, "uv.lock")),
  );
  const marimo = await prepareMarimo(version);
  const upstreamFrontend = join(marimo.path, "frontend");
  const modules = join(upstreamFrontend, "node_modules");
  const htmlLanguage = resolveOwnedDependency(
    upstreamFrontend,
    "@uiw/codemirror-extensions-langs",
    "@codemirror/lang-html",
  );
  const cssLanguage = resolveOwnedDependency(
    upstreamFrontend,
    "@uiw/codemirror-extensions-langs",
    "@codemirror/lang-css",
  );
  const htmx = fileURLToPath(import.meta.resolve("htmx.org")).replace(
    /\.js$/,
    ".d.ts",
  );
  const nodeTypes = resolveProjectDependency(
    upstreamFrontend,
    "@types/node/index.d.ts",
  );
  const temporary = await Deno.makeTempDir({
    prefix: "marimo-studio-typecheck-",
  });
  const configPath = join(temporary, "tsconfig.json");
  const config = {
    extends: join(upstreamFrontend, "tsconfig.json"),
    compilerOptions: {
      erasableSyntaxOnly: false,
      incremental: false,
      noEmit: true,
      paths: {
        "@codemirror/state": [join(modules, "@codemirror", "state")],
        "@codemirror/view": [join(modules, "@codemirror", "view")],
        "@codemirror/language": [join(modules, "@codemirror", "language")],
        "@codemirror/autocomplete": [
          join(modules, "@codemirror", "autocomplete"),
        ],
        "@codemirror/commands": [join(modules, "@codemirror", "commands")],
        "@codemirror/search": [join(modules, "@codemirror", "search")],
        "@codemirror/lang-html": [htmlLanguage],
        "@codemirror/lang-css": [cssLanguage],
        "@/core/codemirror/rtc/extension": [
          join(
            here,
            "src",
            "marimo-adapter",
            "server-only-rtc.ts",
          ),
        ],
        "@/*": [join(upstreamFrontend, "src", "*")],
        "@marimo-team/frontend/unstable_internal/*": [
          join(upstreamFrontend, "src", "*"),
        ],
        "@uiw/react-codemirror": [
          join(modules, "@uiw", "react-codemirror"),
        ],
        "htmx.org": [htmx],
        "jotai": [join(modules, "jotai")],
        "jotai/*": [join(modules, "jotai", "*")],
        "react": [join(modules, "@types", "react", "index.d.ts")],
        "react/*": [join(modules, "@types", "react", "*")],
        "react-dom": [join(modules, "@types", "react-dom", "index.d.ts")],
        "react-dom/*": [join(modules, "@types", "react-dom", "*")],
      },
    },
    files: [
      nodeTypes,
      join(upstreamFrontend, "node_modules", "vite", "client.d.ts"),
      join(upstreamFrontend, "src", "custom.d.ts"),
      join(here, "src", "main.ts"),
      join(here, "src", "studio.ts"),
      join(here, "src", "marimo-adapter", "runtime.tsx"),
      join(here, "src", "marimo-adapter", "cell-views.tsx"),
      join(here, "src", "marimo-adapter", "source-editor.tsx"),
      join(here, "src", "marimo-adapter", "server-only-bridge.ts"),
      join(here, "src", "marimo-adapter", "server-only-rtc.ts"),
    ],
    include: [],
  };

  try {
    await Deno.writeTextFile(
      configPath,
      JSON.stringify(config, null, 2) + "\n",
    );
    const result = await new Deno.Command("corepack", {
      args: ["pnpm", "exec", "tsgo", "--project", configPath],
      cwd: marimo.path,
      stdout: "inherit",
      stderr: "inherit",
    }).output();
    if (!result.success) {
      throw new Error(`Frontend type-check exited with status ${result.code}`);
    }
  } finally {
    await Deno.remove(temporary, { recursive: true });
  }
};

if (import.meta.main) {
  await typecheck();
}
