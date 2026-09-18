import { access, mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vite-plus/test";

import {
  type ExamplePublicationFileSystem,
  type ExamplePublicationPaths,
  publishExamples,
  validatePreparedExample,
} from "./example-publication.ts";

interface PublicationFixture {
  paths: ExamplePublicationPaths;
  root: string;
}

const createFixture = async (current: boolean): Promise<PublicationFixture> => {
  const root = await mkdtemp(join(tmpdir(), "marimo-studio-docs-publication-"));
  const paths = {
    destination: join(root, "public", "examples"),
    previous: join(root, "cache", "examples-previous"),
    staging: join(root, "cache", "examples-staging"),
  };
  await mkdir(paths.staging, { recursive: true });
  await writeFile(join(paths.staging, "version.txt"), "new");
  if (current) {
    await mkdir(paths.destination, { recursive: true });
    await writeFile(join(paths.destination, "version.txt"), "current");
  }
  return { paths, root };
};

const withFixture = async (
  current: boolean,
  run: (fixture: PublicationFixture) => Promise<void>,
): Promise<void> => {
  const fixture = await createFixture(current);
  try {
    await run(fixture);
  } finally {
    await rm(fixture.root, { force: true, recursive: true });
  }
};

const expectMissing = async (path: string): Promise<void> => {
  await expect(access(path)).rejects.toThrow();
};

const fileSystemFailingRename = (
  sourceToFail: string,
  failure: Error,
): ExamplePublicationFileSystem => ({
  remove: (path) => rm(path, { force: true, recursive: true }),
  rename: async (source, destination) => {
    if (source === sourceToFail) {
      throw failure;
    }
    await rename(source, destination);
  },
});

test("publishes the staged examples and removes the previous tree", async () => {
  await withFixture(true, async (fixture) => {
    await publishExamples(fixture.paths);

    expect(await readFile(join(fixture.paths.destination, "version.txt"), "utf8")).toBe("new");
    await expectMissing(fixture.paths.staging);
    await expectMissing(fixture.paths.previous);
  });
});

test("rejects a replacement failure when no previous publication exists", async () => {
  await withFixture(false, async (fixture) => {
    const failure = new Error("replacement failed");
    await expect(
      publishExamples(fixture.paths, fileSystemFailingRename(fixture.paths.staging, failure)),
    ).rejects.toBe(failure);

    await expectMissing(fixture.paths.destination);
    await expectMissing(fixture.paths.staging);
    await expectMissing(fixture.paths.previous);
  });
});

test("restores the previous publication when replacement fails", async () => {
  await withFixture(true, async (fixture) => {
    const failure = new Error("replacement failed");
    await expect(
      publishExamples(fixture.paths, fileSystemFailingRename(fixture.paths.staging, failure)),
    ).rejects.toBe(failure);

    expect(await readFile(join(fixture.paths.destination, "version.txt"), "utf8")).toBe("current");
    await expectMissing(fixture.paths.staging);
    await expectMissing(fixture.paths.previous);
  });
});

test("removes staging when the current publication cannot be moved", async () => {
  await withFixture(true, async (fixture) => {
    const failure = new Error("current publication move failed");
    await expect(
      publishExamples(fixture.paths, fileSystemFailingRename(fixture.paths.destination, failure)),
    ).rejects.toBe(failure);

    expect(await readFile(join(fixture.paths.destination, "version.txt"), "utf8")).toBe("current");
    await expectMissing(fixture.paths.staging);
    await expectMissing(fixture.paths.previous);
  });
});

test("accepts a prepared example with its runtime config and manifest", async () => {
  await withFixture(false, async ({ root }) => {
    const view = join(root, "occupancy/monitor/_marimo-studio/views/monitor");
    await mkdir(join(view, "zero-python"), { recursive: true });
    await writeFile(join(view, "config"), JSON.stringify({ runtime: { id: "zero-python" } }));
    await writeFile(join(view, "zero-python/current"), "{}");

    await validatePreparedExample(root, "occupancy", "monitor");
  });
});

test.each(["missing config", "malformed config", "wrong runtime", "missing manifest"])(
  "reports the example publication contract for %s",
  async (fault) => {
    await withFixture(false, async ({ root }) => {
      const view = join(root, "occupancy/monitor/_marimo-studio/views/monitor");
      await mkdir(join(view, "zero-python"), { recursive: true });
      if (fault !== "missing manifest") {
        await writeFile(join(view, "zero-python/current"), "{}");
      }
      if (fault !== "missing config") {
        const config =
          fault === "malformed config"
            ? "{"
            : JSON.stringify({
                runtime: { id: fault === "wrong runtime" ? "wasm" : "zero-python" },
              });
        await writeFile(join(view, "config"), config);
      }

      await expect(validatePreparedExample(root, "occupancy", "monitor")).rejects.toThrow(
        "The occupancy/monitor example must be a complete zero-python export.",
      );
    });
  },
);
