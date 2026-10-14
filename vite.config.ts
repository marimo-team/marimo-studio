import { defineConfig } from "vite-plus";

import { antiSlopIgnorePatterns, antiSlopRules } from "./tools/oxlint/anti-slop/preset.ts";

const generated = [
  "**/__marimo__/**",
  "apps/docs/.vitepress/cache/**",
  "apps/docs/.vitepress/dist/**",
  "apps/e2e/.cache/**",
  "dist/**",
  "packages/marimo-frontend/.cache/**",
  "packages/marimo-studio/src/marimo_studio/_static/**",
];

const providerToolSources = [
  "packages/marimo-studio/src/marimo_studio/view_providers/_builtin/**/analyzer.ts",
  "packages/marimo-studio/src/marimo_studio/view_providers/_builtin/**/analyzers/**",
  "packages/marimo-studio/src/marimo_studio/view_providers/_builtin/**/starters/**",
];

// Example and fixture view projects keep the formatting their starters wrote.
const viewProjects = ["apps/e2e/fixtures/studio/**", "examples/studio/**"];

const ignored = [...generated, ...viewProjects, ...providerToolSources, ...antiSlopIgnorePatterns];

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
      ...antiSlopRules,
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
                "@marimo-team/frontend",
                "@marimo-team/frontend/*",
                "@marimo-team/marimo-export",
                "@marimo-team/marimo-export/*",
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
        files: [".github/actions/pr-validation/select.ts"],
        rules: {
          "eslint/no-restricted-imports": [
            "error",
            {
              patterns: [
                {
                  group: ["*", "!node:*", "!node:*/*"],
                  message: "The selector runs before the workspace installs dependencies.",
                },
              ],
            },
          ],
        },
      },
      {
        files: ["**/*.test.ts", "**/*.test.tsx", "**/tests/**"],
        rules: {
          "typescript/unbound-method": "off",
        },
      },
      {
        // oxlint 1.79 added React Compiler rules to correctness. These files
        // predate them and use ref, portal host, and effect patterns the rules
        // report. New files keep the rules.
        files: [
          "packages/marimo-frontend/src/radix-compose-refs.ts",
          "packages/presentation/src/prepared/portals.tsx",
          "packages/presentation/src/runtime/cells/CellOutput.tsx",
          "packages/presentation/src/runtime/cells/DuplicateCellPortal.tsx",
          "packages/presentation/src/runtime/cells/use-cell-host.ts",
          "packages/presentation/src/runtime/outputs/DuplicateOutputPortal.tsx",
          "packages/presentation/src/runtime/outputs/use-output-host.ts",
          "packages/studio/src/app/StudioHost.tsx",
          "packages/studio/src/features/navigation/RuntimeMenu.tsx",
          "packages/studio/src/features/navigation/WorkspaceMenu.tsx",
          "packages/studio/src/features/source-editor/SourceEditor.tsx",
          "packages/studio/src/features/source-editor/SourcePane.tsx",
          "packages/studio/src/features/source-editor/SourceProjectDetails.tsx",
          "packages/studio/src/features/views/FirstViewToolbar.tsx",
          "packages/studio/src/features/views/ViewMenu.tsx",
          "packages/studio/src/features/views/useViewMenu.ts",
          "packages/studio/src/features/workspace/PaneMenu.tsx",
          "packages/studio/src/features/workspace/TrustedFrame.tsx",
          "packages/studio/src/shared/editor-workspace.ts",
          "packages/studio/src/shared/useDisclosureMenu.ts",
        ],
        rules: {
          "react/immutability": "off",
          "react/preserve-manual-memoization": "off",
          "react/refs": "off",
          "react/set-state-in-effect": "off",
        },
      },
    ],
  },
});
