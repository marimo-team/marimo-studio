export const drainPendingTasks = async (pending: ReadonlySet<Promise<void>>): Promise<void> => {
  do {
    await Promise.all(pending);
    await Promise.resolve();
  } while (pending.size > 0);
};
