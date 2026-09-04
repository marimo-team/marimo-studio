export const initialPreviewRuntime = ({
  available,
  configured,
}: {
  available: readonly string[];
  configured: string;
}): string => {
  if (available.includes(configured)) {
    return configured;
  }
  const fallback = available[0];
  if (!fallback) {
    throw new Error("Studio requires at least one preview runtime");
  }
  return fallback;
};
