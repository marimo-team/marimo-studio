import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { resolve } from "node:path";

export const withTemporaryExportRepository = async (root, operation) => {
  await mkdir(root, { recursive: true });
  const repository = await mkdtemp(resolve(root, "static-export-repository-"));
  try {
    return await operation(repository);
  } finally {
    await rm(repository, { force: true, recursive: true });
  }
};
