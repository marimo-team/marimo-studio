/** Pass the port assigned by Portless to either native VitePress server command. */
export const documentationServerArguments = (
  arguments_: string[],
  assignedPort: string | undefined,
): string[] => {
  const [mode] = arguments_;
  if (arguments_.length !== 1 || (mode !== "dev" && mode !== "preview")) {
    throw new Error("Choose the documentation dev or preview command.");
  }
  if (assignedPort === undefined || !/^\d+$/.test(assignedPort)) {
    throw new Error("PORT must be assigned by Portless; run pnpm dev or pnpm preview.");
  }
  const port = Number(assignedPort);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new RangeError("PORT must be a TCP port between 1 and 65535.");
  }
  return [mode, "--host", "127.0.0.1", "--port", String(port), "--strictPort"];
};
