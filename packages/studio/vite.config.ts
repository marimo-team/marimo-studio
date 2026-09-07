import { defineConfig } from "vite-plus";

const contracts = [
  "tests/admission.test.ts",
  "tests/query-remote.test.ts",
  "tests/source-languages.test.ts",
];

export default defineConfig({
  test: {
    pool: "threads",
    projects: [
      {
        extends: true,
        test: { name: "studio-contracts", environment: "node", include: contracts },
      },
      {
        extends: true,
        test: {
          name: "studio-dom",
          environment: "jsdom",
          setupFiles: ["./tests/setup.ts"],
          include: ["tests/**/*.test.{ts,tsx}"],
          exclude: contracts,
        },
      },
    ],
  },
});
