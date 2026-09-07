export const withExportRepository = async (directory, operation) => {
  const previous = process.env.MARIMO_EXPORT_REPOSITORY;
  process.env.MARIMO_EXPORT_REPOSITORY = directory;
  try {
    return await operation();
  } finally {
    if (previous === undefined) delete process.env.MARIMO_EXPORT_REPOSITORY;
    else process.env.MARIMO_EXPORT_REPOSITORY = previous;
  }
};
