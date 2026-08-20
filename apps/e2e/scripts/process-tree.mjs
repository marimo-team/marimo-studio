import { spawn } from "node:child_process";

const killProcessGroup = (pid, signal) => process.kill(pid, signal);

const taskkill = (pid, spawnProcess, timeoutMs) =>
  new Promise((resolve, reject) => {
    const child = spawnProcess("taskkill.exe", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
    let settled = false;
    const settle = (complete) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      complete();
    };
    const timeout = setTimeout(() => {
      settle(() => {
        child.kill();
        reject(new Error(`taskkill did not exit within ${String(timeoutMs)}ms`));
      });
    }, timeoutMs);
    timeout.unref();
    child.once("error", (error) => settle(() => reject(error)));
    child.once("exit", (code, signal) => {
      settle(() => {
        if (code === 0) {
          resolve();
          return;
        }
        reject(
          new Error(
            signal
              ? `taskkill exited after signal ${signal}`
              : `taskkill exited with status ${String(code)}`,
          ),
        );
      });
    });
  });

export const terminateProcessTree = async (
  child,
  signal,
  {
    killProcess = killProcessGroup,
    platform = process.platform,
    spawnProcess = spawn,
    taskkillTimeoutMs = 5_000,
  } = {},
) => {
  if (child.pid === undefined) {
    child.kill(signal);
    return;
  }
  if (platform === "win32") {
    await taskkill(child.pid, spawnProcess, taskkillTimeoutMs);
    return;
  }
  try {
    killProcess(-child.pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") {
      throw error;
    }
  }
};
