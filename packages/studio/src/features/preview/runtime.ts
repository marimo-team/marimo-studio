import type { RuntimeDescriptor } from "@marimo-studio/protocol/runtime-descriptor";

export const initialPreviewRuntime = ({
  available,
  configured,
}: {
  available: readonly RuntimeDescriptor[];
  configured: string;
}): RuntimeDescriptor => {
  const selected = available.find((runtime) => runtime.id === configured);
  if (selected) {
    return selected;
  }
  const fallback = available[0];
  if (!fallback) {
    throw new Error("Studio requires at least one preview runtime");
  }
  return fallback;
};
