export const workerUrl = import.meta.url;

if (typeof document === "undefined") {
  await import("maplibre-gl/dist/maplibre-gl-worker.mjs");
}
