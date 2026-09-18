import { readFile, rename, rm, stat } from "node:fs/promises";
import { join } from "node:path";

export const validatePreparedExample = async (
  root: string,
  family: string,
  view: string,
): Promise<void> => {
  const viewRoot = join(root, family, view, "_marimo-studio", "views", view);
  try {
    // SAFETY: The exporter owns this record. Validate the publication policy even when
    // an interrupted or corrupt previous export is being selectively rebuilt.
    const config = JSON.parse(await readFile(join(viewRoot, "config"), "utf8")) as {
      runtime?: { id?: string };
    } | null;
    if (config?.runtime?.id !== "zero-python") {
      throw new Error("Expected the zero-python runtime.");
    }
    if (!(await stat(join(viewRoot, "zero-python", "current"))).isFile()) {
      throw new Error("Expected a prepared manifest file.");
    }
  } catch (cause) {
    throw new Error(`The ${family}/${view} example must be a complete zero-python export.`, {
      cause,
    });
  }
};

export interface ExamplePublicationPaths {
  destination: string;
  previous: string;
  staging: string;
}

export interface ExamplePublicationFileSystem {
  remove(path: string): Promise<void>;
  rename(source: string, destination: string): Promise<void>;
}

const publicationFileSystem: ExamplePublicationFileSystem = {
  remove: (path) => rm(path, { force: true, recursive: true }),
  rename,
};

const isMissingPath = (error: Error): boolean => "code" in error && error.code === "ENOENT";

const throwPublicationFailures = (failures: unknown[]): never => {
  if (failures.length === 1) {
    throw failures[0];
  }
  throw new AggregateError(failures, "The documentation examples could not be published.");
};

const removeStaging = async (
  staging: string,
  operations: ExamplePublicationFileSystem,
  failures: unknown[],
): Promise<void> => {
  try {
    await operations.remove(staging);
  } catch (error) {
    failures.push(error);
  }
};

export const publishExamples = async (
  paths: ExamplePublicationPaths,
  operations: ExamplePublicationFileSystem = publicationFileSystem,
): Promise<void> => {
  try {
    await operations.remove(paths.previous);
  } catch (error) {
    const failures = [error];
    await removeStaging(paths.staging, operations, failures);
    throwPublicationFailures(failures);
  }

  let movedPrevious = false;
  try {
    await operations.rename(paths.destination, paths.previous);
    movedPrevious = true;
  } catch (error) {
    if (!(error instanceof Error && isMissingPath(error))) {
      const failures = [error];
      await removeStaging(paths.staging, operations, failures);
      throwPublicationFailures(failures);
    }
  }

  try {
    await operations.rename(paths.staging, paths.destination);
  } catch (error) {
    const failures = [error];
    if (movedPrevious) {
      try {
        await operations.rename(paths.previous, paths.destination);
      } catch (restorationError) {
        failures.push(restorationError);
      }
    }
    await removeStaging(paths.staging, operations, failures);
    throwPublicationFailures(failures);
  }

  if (movedPrevious) {
    await operations.remove(paths.previous);
  }
};
