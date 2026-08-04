import { runtimeIdSchema } from "./runtime-config";

export const DEFAULT_RUNTIME_ID = "server";
export const RUNTIME_QUERY_KEY = "runtime";

export const runtimeIdFromSearch = (search: string, fallback = DEFAULT_RUNTIME_ID): string => {
  const value = new URLSearchParams(search).get(RUNTIME_QUERY_KEY);
  const parsed = runtimeIdSchema.safeParse(value);
  return parsed.success ? parsed.data : runtimeIdSchema.parse(fallback);
};

export const selectRuntimeInUrl = (
  source: string,
  runtime: string,
  fallback = DEFAULT_RUNTIME_ID,
): string => {
  const selected = runtimeIdSchema.parse(runtime);
  const defaultRuntime = runtimeIdSchema.parse(fallback);
  const url = new URL(source);
  if (selected === defaultRuntime) {
    url.searchParams.delete(RUNTIME_QUERY_KEY);
  } else {
    url.searchParams.set(RUNTIME_QUERY_KEY, selected);
  }
  return url.toString();
};
