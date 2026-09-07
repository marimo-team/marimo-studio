export const observeServerExit = (child, output) => {
  let stopping = false;
  let failure;
  child.once("error", (error) => {
    if (!stopping) failure ??= error;
  });
  child.once("exit", (code, signal) => {
    if (!stopping) {
      failure ??= new Error(
        `Notebook service exited unexpectedly with ${signal ?? code}\n${output()}`,
      );
    }
  });
  return {
    shutdown: () => {
      stopping = true;
      return failure;
    },
  };
};
