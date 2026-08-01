const decoder = new TextDecoder();

export const run = async (
  command: string,
  args: string[],
  cwd: string,
): Promise<void> => {
  const result = await new Deno.Command(command, {
    args,
    cwd,
    stdout: "inherit",
    stderr: "inherit",
  }).output();
  if (!result.success) {
    throw new Error(`${command} exited with status ${result.code}`);
  }
};

export const capture = async (
  command: string,
  args: string[],
  cwd: string,
): Promise<string> => {
  const result = await new Deno.Command(command, { args, cwd }).output();
  if (!result.success) {
    const detail = decoder.decode(result.stderr).trim();
    throw new Error(
      `${command} exited with status ${result.code}${
        detail ? `: ${detail}` : ""
      }`,
    );
  }
  return decoder.decode(result.stdout).trim();
};
