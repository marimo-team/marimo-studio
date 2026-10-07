// Workflows run this selector with the runner's preinstalled Node before the
// workspace installs dependencies. It imports Node built-ins only and relies
// on type stripping, which Node enables by default from 22.18.
import { appendFileSync } from "node:fs";

interface DeferredRule {
  readonly filter?: unknown;
  readonly escalate?: unknown;
}

interface DeferredContract {
  readonly filters: readonly string[];
  readonly escalate: string;
}

const {
  VALIDATION_MODE,
  VALIDATION_EVENT,
  VALIDATION_FILTERS,
  DEFERRED_FILTERS,
  PATH_FILTERS_JSON,
  GITHUB_OUTPUT,
} = process.env;
if (VALIDATION_MODE !== "full" && VALIDATION_MODE !== "changed" && VALIDATION_MODE !== "reuse") {
  throw new Error(`Invalid validation mode: ${VALIDATION_MODE}`);
}
const outputName = /^[a-z_]+$/;
// oxlint-disable-next-line anti-slop/no-runtime-typeof, anti-slop/no-unknown-parameters -- Workflow JSON is decoded without a schema library.
const isString = (value: unknown): value is string => typeof value === "string";
const names: unknown = JSON.parse(VALIDATION_FILTERS ?? "[]");
if (
  !Array.isArray(names) ||
  !names.every(isString) ||
  !names.every((name) => outputName.test(name)) ||
  new Set(names).size !== names.length
) {
  throw new Error("Validation filters must be a list of distinct output names");
}
// A deferred contract runs after merge whenever one of its filters matched. A
// pull request runs it only when its escalation filter also matched.
const rules: Readonly<Record<string, DeferredRule | null>> = JSON.parse(DEFERRED_FILTERS ?? "{}");
const deferred = Object.entries(rules).map(([name, rule]): [string, DeferredContract] => {
  const owned: unknown = isString(rule?.filter) ? [rule.filter] : rule?.filter;
  const escalate: unknown = rule?.escalate;
  if (
    !outputName.test(name) ||
    names.includes(name) ||
    !Array.isArray(owned) ||
    owned.length === 0 ||
    !owned.every(isString) ||
    !isString(escalate)
  ) {
    throw new Error("Deferred filters must map new output names to filter and escalate names");
  }
  return [name, { filters: owned, escalate }];
});
if (names.length + deferred.length === 0) {
  throw new Error("Select at least one validation contract");
}
if (
  deferred.length > 0 &&
  VALIDATION_MODE !== "full" &&
  VALIDATION_EVENT !== "push" &&
  VALIDATION_EVENT !== "pull_request"
) {
  throw new Error(`Deferred contracts need a push or pull_request event: ${VALIDATION_EVENT}`);
}

const filters: Readonly<Partial<Record<string, string>>> = JSON.parse(PATH_FILTERS_JSON ?? "{}");
const matched = (name: string): boolean => {
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
