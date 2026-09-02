import { access, mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vite-plus/test";

import {
  type ExamplePublicationFileSystem,
  type ExamplePublicationPaths,
  publishExamples,
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
