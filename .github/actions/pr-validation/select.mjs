import { appendFileSync } from "node:fs";

const { VALIDATION_MODE, VALIDATION_FILTERS, PATH_FILTERS_JSON, GITHUB_OUTPUT } = process.env;
if (!["full", "changed", "reuse"].includes(VALIDATION_MODE)) {
  throw new Error(`Invalid validation mode: ${VALIDATION_MODE}`);
}
const names = JSON.parse(VALIDATION_FILTERS ?? "null");
if (
  !Array.isArray(names) ||
  names.length === 0 ||
  names.some((name) => typeof name !== "string" || !/^[a-z_]+$/.test(name)) ||
  new Set(names).size !== names.length
) {
  throw new Error("Validation filters must be a nonempty list of distinct output names");
}
const filters = JSON.parse(PATH_FILTERS_JSON ?? "{}");
const lines = names.map((name) => {
  const selected =
    VALIDATION_MODE === "changed" ? filters[name] : String(VALIDATION_MODE === "full");
  if (selected !== "true" && selected !== "false") {
    throw new Error(`Missing or invalid path-filter result: ${name}`);
  }
  return `${name}=${selected}\n`;
});
if (!GITHUB_OUTPUT) throw new Error("GITHUB_OUTPUT is required");
appendFileSync(GITHUB_OUTPUT, lines.join(""));
