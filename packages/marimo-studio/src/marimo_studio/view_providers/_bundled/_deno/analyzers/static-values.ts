export type ProjectionKind = "cell" | "output" | "value";

export type StaticDiagnosticCode = "projection-target-domain-invalid";

export type StaticValue =
  | {
    readonly kind: "string";
    readonly value: string;
  }
  | { readonly kind: "other" }
  | { readonly kind: "array"; readonly items: readonly StaticValue[] }
  | {
    readonly kind: "record";
    readonly entries: ReadonlyMap<string, StaticValue>;
  };

export type StaticResult =
  | { readonly status: "bounded"; readonly values: readonly StaticValue[] }
  | { readonly status: "dynamic" }
  | {
    readonly status: "invalid";
    readonly code: StaticDiagnosticCode;
    readonly message: string;
  };

type InvalidStaticResult = Extract<
  StaticResult,
  { readonly status: "invalid" }
>;

export const bounded = (...values: StaticValue[]): StaticResult => ({
  status: "bounded",
  values,
});

export const dynamic = (): StaticResult => ({ status: "dynamic" });

export const invalid = (
  code: StaticDiagnosticCode,
  message: string,
): InvalidStaticResult => ({
  status: "invalid",
  code,
  message,
});

export const stringValue = (value: string): StaticValue => ({
  kind: "string",
  value,
});

export const otherValue = (): StaticValue => ({ kind: "other" });

export const arrayItems = (result: StaticResult): StaticResult => {
  if (result.status !== "bounded") return result;
  const values: StaticValue[] = [];
  for (const value of result.values) {
    if (value.kind !== "array") return dynamic();
    values.push(...value.items);
  }
  return bounded(...values);
};

export const propertyValues = (
  result: StaticResult,
  property: string,
): StaticResult => {
  if (result.status !== "bounded") return result;
  const values: StaticValue[] = [];
  for (const value of result.values) {
    if (value.kind !== "record") return dynamic();
    const member = value.entries.get(property);
    if (member === undefined) return dynamic();
    values.push(member);
  }
  return bounded(...values);
};

const canonicalTargets = (values: readonly StaticValue[]): string[] | null => {
  const targets: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (value.kind !== "string") return null;
    const target = value.value.trim();
    if (target.length === 0) return null;
    if (!seen.has(target)) {
      seen.add(target);
      targets.push(target);
    }
  }
  return targets;
};

export const targetsFromResult = (
  _kind: ProjectionKind,
  result: StaticResult,
): readonly string[] | StaticResult => {
  if (result.status !== "bounded") return result;
  if (result.values.length === 0) {
    return invalid(
      "projection-target-domain-invalid",
      "Projection target collection requires at least one target string",
    );
  }
  const targets = canonicalTargets(result.values);
  if (targets === null) {
    return invalid(
      "projection-target-domain-invalid",
      "Projection target collection requires non-empty target strings",
    );
  }
  return targets;
};
