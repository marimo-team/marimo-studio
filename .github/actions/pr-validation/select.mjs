import { appendFileSync } from "node:fs";

const {
  VALIDATION_MODE,
  VALIDATION_EVENT,
  VALIDATION_FILTERS,
  DEFERRED_FILTERS,
  PATH_FILTERS_JSON,
  GITHUB_OUTPUT,
} = process.env;
if (!["full", "changed", "reuse"].includes(VALIDATION_MODE)) {
  throw new Error(`Invalid validation mode: ${VALIDATION_MODE}`);
}
const outputName = /^[a-z_]+$/;
const names = JSON.parse(VALIDATION_FILTERS ?? "[]");
if (
  !Array.isArray(names) ||
  names.some((name) => typeof name !== "string" || !outputName.test(name)) ||
  new Set(names).size !== names.length
) {
  throw new Error("Validation filters must be a list of distinct output names");
}
// A deferred contract runs after merge whenever one of its filters matched. A
// pull request runs it only when its escalation filter also matched.
const deferred = Object.entries(JSON.parse(DEFERRED_FILTERS ?? "{}")).map(([name, rule]) => [
  name,
  {
    filters: typeof rule?.filter === "string" ? [rule.filter] : rule?.filter,
    escalate: rule?.escalate,
  },
]);
if (
  deferred.some(
    ([name, rule]) =>
      !outputName.test(name) ||
      names.includes(name) ||
      !Array.isArray(rule.filters) ||
      rule.filters.length === 0 ||
      rule.filters.some((filter) => typeof filter !== "string") ||
      typeof rule.escalate !== "string",
  )
) {
  throw new Error("Deferred filters must map new output names to filter and escalate names");
}
if (names.length + deferred.length === 0) {
  throw new Error("Select at least one validation contract");
}
if (
  deferred.length > 0 &&
  VALIDATION_MODE !== "full" &&
  !["push", "pull_request"].includes(VALIDATION_EVENT)
) {
  throw new Error(`Deferred contracts need a push or pull_request event: ${VALIDATION_EVENT}`);
}

const filters = JSON.parse(PATH_FILTERS_JSON ?? "{}");
const matched = (name) => {
  const value = filters[name];
  if (value !== "true" && value !== "false") {
    throw new Error(`Missing or invalid path-filter result: ${name}`);
  }
  return value === "true";
};
const lines = names.map((name) => {
  const selected = VALIDATION_MODE === "changed" ? matched(name) : VALIDATION_MODE === "full";
  return `${name}=${selected}\n`;
});
for (const [name, { filters: owned, escalate }] of deferred) {
  const selected =
    VALIDATION_MODE === "full" ||
    (owned.map(matched).some(Boolean) && (VALIDATION_EVENT === "push" || matched(escalate)));
  lines.push(`${name}=${selected}\n`);
}
if (!GITHUB_OUTPUT) throw new Error("GITHUB_OUTPUT is required");
appendFileSync(GITHUB_OUTPUT, lines.join(""));
