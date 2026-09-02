try {
  const { assertPreparedMarimoSource } = await import("./source.mjs");
  await assertPreparedMarimoSource();
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Marimo frontend readiness check failed: ${detail}\n`);
  process.stderr.write("Run 'make setup' to prepare the pinned frontend source.\n");
  process.exitCode = 1;
}
