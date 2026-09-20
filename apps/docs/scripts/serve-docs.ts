import { documentationServerArguments } from "./server-arguments.ts";

process.argv.splice(
  2,
  process.argv.length,
  ...documentationServerArguments(process.argv.slice(2), process.env.PORT),
);
const cli = import.meta.resolve("vitepress/dist/node/cli.js");
await import(cli);
