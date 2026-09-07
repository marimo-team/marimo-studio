import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vite-plus/test";
import { z } from "zod";

import {
  parseStudioPreparedManifest,
  parseZeroPythonRuntimeData,
  StudioPreparedManifestSource,
  validateStudioPreparedManifest,
} from "../src/zero-python/metadata.ts";
import { notebookExportFixture, projectionNames, studioManifest } from "./zero-python-fixture.ts";

const hostBoundary = z
  .strictObject({
    schema: z.literal("marimo-studio.projection-host-boundary.v1"),
    character: z.string().min(1),
    maximum_utf8_bytes: z.number().int().positive(),
    valid_repetitions: z.number().int().positive(),
    invalid_suffix: z.string().min(1),
  })
  .parse(
    JSON.parse(
      readFileSync(
        new URL(
          "../../../packages/protocol/fixtures/projection-host-boundary.json",
          import.meta.url,
        ),
        "utf8",
      ),
    ),
  );

describe("Studio prepared metadata", () => {
  it("parses an exact Studio envelope around the package-owned prepared manifest", () => {
    const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });

    const parsed = parseStudioPreparedManifest(
      studioManifest(notebookExport, { mode: "baseline" }),
    );

    expect(parsed.prepared).toMatchObject({
      schema: "marimo-export.prepared.v1",
      exportUrl: notebookExport.base.href,
      stateFingerprint: notebookExport.defaultState.fingerprint,
    });
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.projections)).toBe(true);
  });

  it("rejects the previous flat manifest and unknown Studio fields", () => {
    const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });
    const current = studioManifest(notebookExport, { mode: "baseline" });

    expect(() =>
      parseStudioPreparedManifest({
        schema: 1,
        instance: notebookExport.identity,
        exportUrl: notebookExport.base.href,
        inputs: { mode: "baseline" },
      }),
    ).toThrow(/metadata is invalid/);
    expect(() => parseStudioPreparedManifest({ ...current, fallback: "server" })).toThrow(
      /metadata is invalid/,
    );
  });

  it("bounds authored host selectors and exported output names", () => {
    const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });
    const current = studioManifest(notebookExport, { mode: "baseline" });
    const host = hostBoundary.character.repeat(hostBoundary.valid_repetitions);
    const invalidHost = host + hostBoundary.invalid_suffix;

    expect(
      parseStudioPreparedManifest({
        ...current,
        projections: { values: { [host]: "value:doubled" }, outputs: {}, cells: {} },
      }),
    ).toBeDefined();
    expect(new TextEncoder().encode(host)).toHaveLength(hostBoundary.maximum_utf8_bytes);
    expect(() =>
      parseStudioPreparedManifest({
        ...current,
        projections: { values: { [invalidHost]: "value:doubled" }, outputs: {}, cells: {} },
      }),
    ).toThrow(/metadata is invalid/);
    expect(() =>
      parseStudioPreparedManifest({
        ...current,
        projections: {
          values: { metric: `value:${"x".repeat(250)}` },
          outputs: {},
          cells: {},
        },
      }),
    ).toThrow(/metadata is invalid/);
  });

  it("validates view, plan, document identity, and readable output coverage", () => {
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }],
      outputNames: Object.values(projectionNames),
    });
    const metadata = parseStudioPreparedManifest(
      studioManifest(notebookExport, { mode: "baseline" }, true),
    );
    const context = {
      view: "dashboard",
      planDigest: "3".repeat(64),
    };

    expect(() =>
      validateStudioPreparedManifest(metadata, context, notebookExport, notebookExport.identity),
    ).not.toThrow();
    expect(() =>
      validateStudioPreparedManifest(
        metadata,
        { ...context, view: "other" },
        notebookExport,
        notebookExport.identity,
      ),
    ).toThrow(/describes view/);
    expect(() =>
      validateStudioPreparedManifest(
        { ...metadata, planDigest: "4".repeat(64) },
        context,
        notebookExport,
        notebookExport.identity,
      ),
    ).toThrow(/projection plan/);
    expect(() =>
      validateStudioPreparedManifest(metadata, context, notebookExport, "f".repeat(64)),
    ).toThrow(/runtime instance/);
    expect(() =>
      parseStudioPreparedManifest({
        ...studioManifest(notebookExport, { mode: "baseline" }, true),
        projections: {
          ...studioManifest(notebookExport, { mode: "baseline" }, true).projections,
          values: { metric: projectionNames.output },
        },
      }),
    ).toThrow(/metadata is invalid/);
  });

  it("keeps export identity stable when an authored host is renamed", () => {
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }],
      outputNames: [projectionNames.value],
    });
    const initial = parseStudioPreparedManifest({
      ...studioManifest(notebookExport, { mode: "baseline" }),
      projections: { values: { metric: projectionNames.value }, outputs: {}, cells: {} },
    });
    const renamed = parseStudioPreparedManifest({
      ...studioManifest(notebookExport, { mode: "baseline" }),
      projections: { values: { headline: projectionNames.value }, outputs: {}, cells: {} },
    });

    expect(() =>
      validateStudioPreparedManifest(
        initial,
        {
          view: "dashboard",
          planDigest: "3".repeat(64),
        },
        notebookExport,
        notebookExport.identity,
      ),
    ).not.toThrow();
    expect(() =>
      validateStudioPreparedManifest(
        renamed,
        {
          view: "dashboard",
          planDigest: "3".repeat(64),
        },
        notebookExport,
        notebookExport.identity,
      ),
    ).not.toThrow();
    expect(initial.projections.values.metric).toBe(renamed.projections.values.headline);
  });

  it("allows several authored hosts to share one exported source", () => {
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }],
      outputNames: [projectionNames.cell],
    });
    const metadata = parseStudioPreparedManifest({
      ...studioManifest(notebookExport, { mode: "baseline" }),
      projections: {
        values: {},
        outputs: {},
        cells: { headline: projectionNames.cell, summary: projectionNames.cell },
      },
    });

    expect(() =>
      validateStudioPreparedManifest(
        metadata,
        {
          view: "dashboard",
          planDigest: "3".repeat(64),
        },
        notebookExport,
        notebookExport.identity,
      ),
    ).not.toThrow();
  });

  it("fetches without caching and associates metadata with its prepared record", async () => {
    const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });
    const manifest = studioManifest(notebookExport, { mode: "baseline" });
    const fetcher = vi.fn(async () => new Response(JSON.stringify(manifest)));
    const source = new StudioPreparedManifestSource(
      () => ({
        view: "dashboard",
        planDigest: "3".repeat(64),
      }),
      fetcher,
    );
    const url = new URL("https://example.test/current");
    const prepared = await source.fetch(url, {}, notebookExport.identity);

    expect(source.metadata(prepared).view).toBe("dashboard");
    expect(fetcher).toHaveBeenCalledWith(
      url,
      expect.objectContaining({ cache: "no-store", headers: { Accept: "application/json" } }),
    );
  });

  it("rejects a stale manifest from another runtime binding", async () => {
    const selected = notebookExportFixture({ identity: "1".repeat(64), inputs: [{ mode: "one" }] });
    const stale = notebookExportFixture({ identity: "2".repeat(64), inputs: [{ mode: "two" }] });
    const source = new StudioPreparedManifestSource(
      () => ({
        view: "dashboard",
        planDigest: "3".repeat(64),
      }),
      async () => new Response(JSON.stringify(studioManifest(stale, stale.defaultState.inputs))),
    );
    await expect(
      source.fetch(new URL("https://example.test/current"), {}, selected.identity),
    ).rejects.toThrow(/runtime instance/);
  });

  it("accepts a current-route rotation after anchoring the initial instance", async () => {
    const initial = notebookExportFixture({
      identity: "1".repeat(64),
      inputs: [{ mode: "initial" }],
    });
    const rotated = notebookExportFixture({
      identity: "2".repeat(64),
      inputs: [{ mode: "rotated" }],
    });
    let manifest = studioManifest(initial, initial.defaultState.inputs);
    const source = new StudioPreparedManifestSource(
      () => ({
        view: "dashboard",
        planDigest: "3".repeat(64),
      }),
      async () => new Response(JSON.stringify(manifest)),
    );
    const url = new URL("https://example.test/current");
    const prepared = await source.fetch(url, {}, initial.identity);
    manifest = studioManifest(rotated, rotated.defaultState.inputs);

    await expect(source.fetch(url)).resolves.toMatchObject({ instance: rotated.identity });

    expect(source.metadata(prepared).prepared.instance).toBe(initial.identity);
  });

  it("retains the current and rollback export identities across refreshes", async () => {
    const exports = ["1", "2", "3"].map((digit) =>
      notebookExportFixture({ identity: digit.repeat(64), inputs: [{ mode: digit }] }),
    );
    let manifest = studioManifest(exports[0]!, exports[0]!.defaultState.inputs);
    const source = new StudioPreparedManifestSource(
      () => ({
        view: "dashboard",
        planDigest: "3".repeat(64),
      }),
      async () => new Response(JSON.stringify(manifest)),
    );
    const url = new URL("https://example.test/current");
    for (const [index, notebookExport] of exports.entries()) {
      manifest = studioManifest(notebookExport, notebookExport.defaultState.inputs);
      await source.fetch(url, {}, index === 0 ? notebookExport.identity : undefined);
      source.remember(notebookExport);
    }
    const fetchWithWrongDocument = (notebookExport: (typeof exports)[number]) => {
      manifest = {
        ...studioManifest(notebookExport, notebookExport.defaultState.inputs),
        document_sha256: "f".repeat(64),
      };
      return source.fetch(url);
    };

    await expect(fetchWithWrongDocument(exports[1]!)).rejects.toThrow(/not match the immutable/);
    await expect(fetchWithWrongDocument(exports[2]!)).rejects.toThrow(/not match the immutable/);
    await expect(fetchWithWrongDocument(exports[0]!)).resolves.toBeDefined();
  });

  it("parses only the runtime locator and expected plan digest", () => {
    expect(
      parseZeroPythonRuntimeData({
        manifestUrl: "./zero-python/current",
        planDigest: "3".repeat(64),
      }),
    ).toEqual({ manifestUrl: "./zero-python/current", planDigest: "3".repeat(64) });
    expect(() =>
      parseZeroPythonRuntimeData({
        manifestUrl: "./zero-python/current",
        planDigest: "3".repeat(64),
        view: "dashboard",
      }),
    ).toThrow(/runtime data is invalid/);
  });
});
