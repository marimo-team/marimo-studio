try {
  // Importing source.ts validates the pinned patch identity, so its failures
  // also report the setup instructions below.
  const { assertPreparedMarimoSource } = await import("./source.ts");
  await assertPreparedMarimoSource();
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Marimo frontend readiness check failed: ${detail}\n`);
  process.stderr.write("Run 'make setup' to prepare the pinned frontend source.\n");
  process.exitCode = 1;
}
