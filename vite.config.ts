import { defineConfig } from "vite-plus";

const generated = [
  "**/__marimo__/**",
  "apps/docs/.vitepress/cache/**",
  "apps/docs/.vitepress/dist/**",
  "dist/**",
  "packages/marimo-frontend/.cache/**",
  "packages/marimo-studio/src/marimo_studio/_static/**",
];

const agentTooling = [
  ".agent/**",
  ".agents/**",
  ".claude/**",
  ".codex/**",
  ".continue/**",
  ".cursor/**",
  ".gemini/**",
  ".opencode/**",
  ".pi/**",
  ".roo/**",
  ".windsurf/**",
  "tools/oxlint/anti-slop/**",
];

const ignored = [...generated, ...agentTooling];

const studioPackageRestrictedImports = [
  "@marimo-studio/marimo-frontend",
  "@marimo-studio/marimo-frontend/*",
  "@marimo-studio/presentation",
  "@marimo-studio/presentation/*",
  "@marimo-studio/studio",
  "@marimo-studio/studio/*",
  "@marimo-team/frontend",
  "@marimo-team/frontend/*",
  "@/*",
  "../**/marimo-frontend/**",
  "../**/presentation/**",
  "../**/protocol/**",
  "htmx.org",
];

export default defineConfig({
  fmt: {
    ignorePatterns: ignored,
    sortImports: {
      groups: [
        "type-import",
        ["value-builtin", "value-external"],
        "type-internal",
        "value-internal",
        ["type-parent", "type-sibling", "type-index"],
        ["value-parent", "value-sibling", "value-index"],
        "unknown",
      ],
    },
  },
  lint: {
    categories: {
      correctness: "error",
    },
    env: {
      browser: true,
      builtin: true,
    },
    ignorePatterns: ignored,
    jsPlugins: [
      { name: "anti-slop", specifier: "./tools/oxlint/anti-slop/index.ts" },
      { name: "vite-plus", specifier: "vite-plus/oxlint-plugin" },
    ],
    options: {
      denyWarnings: true,
      reportUnusedDisableDirectives: "error",
      typeAware: true,
      typeCheck: true,
    },
    plugins: ["import", "react", "typescript", "unicorn"],
    rules: {
      "anti-slop/no-chained-type-assertions": "error",
      "anti-slop/no-conditional-empty-object-spread": "error",
      "anti-slop/no-known-value-widening": "error",
      "anti-slop/no-module-mocking": "error",
      "anti-slop/no-object-parameters": "error",
      "anti-slop/no-reflect-apply": "error",
      "anti-slop/no-reflect-get": "error",
      "anti-slop/no-runtime-typeof": "error",
      "anti-slop/no-shape-in-symbol-names": "error",
      "anti-slop/no-unknown-parameters": "error",
      "anti-slop/no-unknown-returns": "error",
      "anti-slop/no-unknown-type-aliases": "error",
      "anti-slop/no-unsafe-dictionary-type": "error",
      "anti-slop/no-widen-then-assert": "error",
      "anti-slop/require-safety-comment-for-type-assertion": "error",
      "eslint/no-nested-ternary": "error",
      "import/no-cycle": "error",
      "import/no-duplicates": "error",
      "import/no-self-import": "error",
      "typescript/consistent-type-imports": "error",
      "typescript/no-import-type-side-effects": "error",
      "vite-plus/prefer-vite-plus-imports": "error",
    },
    overrides: [
      {
        files: ["apps/browser/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [
                "@marimo-studio/protocol",
                "@marimo-studio/protocol/*",
                "@marimo-team/frontend",
                "@marimo-team/frontend/*",
                "@/*",
                "../**/marimo-frontend/**",
                "../**/presentation/src/**",
                "../**/protocol/**",
                "../**/studio/src/**",
              ],
            },
          ],
        },
      },
      {
        files: ["packages/marimo-frontend/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: ["@marimo-studio/*"],
            },
          ],
        },
      },
      {
        files: ["packages/runtime/src/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [
                "@marimo-studio/marimo-frontend",
                "@marimo-studio/marimo-frontend/*",
                "@marimo-studio/presentation",
                "@marimo-studio/presentation/*",
                "@marimo-studio/studio",
                "@marimo-studio/studio/*",
                "@marimo-team/*",
                "htmx.org",
                "jotai",
                "react",
                "react-dom",
                "react-dom/*",
              ],
            },
          ],
        },
      },
      {
        files: ["packages/presentation/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [
                "@marimo-studio/studio",
                "@marimo-studio/studio/*",
                "@marimo-team/frontend",
                "@marimo-team/frontend/*",
                "@/*",
                "../**/marimo-frontend/**",
                "../**/protocol/**",
                "../**/studio/**",
              ],
            },
          ],
        },
      },
      {
        files: ["packages/studio/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: studioPackageRestrictedImports,
            },
          ],
        },
      },
      {
        files: ["packages/studio/src/features/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [...studioPackageRestrictedImports, "../**/app/**"],
            },
          ],
        },
      },
      {
        files: ["packages/studio/src/shared/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [...studioPackageRestrictedImports, "../**/app/**", "../**/features/**"],
            },
          ],
        },
      },
      {
        files: ["packages/protocol/src/**"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [
                "@marimo-studio/*",
                "@marimo-team/*",
                "htmx.org",
                "jotai",
                "node:*",
                "react",
                "react-dom",
                "react-dom/*",
                "../**/marimo-frontend/**",
                "../**/presentation/**",
                "../**/studio/**",
              ],
            },
          ],
          "eslint/no-restricted-globals": [
            "error",
            "document",
            "EventSource",
            "fetch",
            "WebSocket",
            "window",
            "XMLHttpRequest",
          ],
        },
      },
      {
        files: ["**/*.test.ts", "**/*.test.tsx", "**/tests/**"],
        rules: {
          "typescript/unbound-method": "off",
        },
      },
    ],
  },
});
