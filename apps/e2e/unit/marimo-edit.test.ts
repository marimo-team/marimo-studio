import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { expect, test } from "vite-plus/test";

import { appDirectory, repositoryDirectory } from "../scripts/paths.ts";

const compatibilityDirectory = resolve(appDirectory, "scripts/_compat");
const launcher = resolve(compatibilityDirectory, "server.py");
const python = resolve(
  repositoryDirectory,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const ownerNonce = "a".repeat(64);

const runPython = (source: string) =>
  spawnSync(python, ["-c", source], {
    cwd: repositoryDirectory,
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
  });

const importLauncher = `import sys\nsys.path.insert(0, ${JSON.stringify(compatibilityDirectory)})\nimport server`;

test("rejects a different pinned Marimo version", () => {
  const result = runPython(`${importLauncher}
server.version = lambda name: "0.25.0"
server.configure_editor_fixture()
`);
  expect(result.status).not.toBe(0);
  expect(result.stderr).toContain("expected version 0.24.2, found 0.25.0");
});

test("retains its bound socket through activation and publishes only when claimed", () => {
  const result = runPython(`${importLauncher}
import errno, json, os, socket, tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as directory:
    receipt = Path(directory) / "endpoint"
    os.environ["MARIMO_STUDIO_E2E_ENDPOINT_FILE"] = str(receipt)
    os.environ["MARIMO_STUDIO_E2E_PROCESS_OWNER"] = "${ownerNonce}"
    claimed = []
    def consume(instance, sockets):
        listener, = sockets
        claimed.append(listener)
        port = listener.getsockname()[1]
        assert json.loads(receipt.read_text()) == {
            "ownerNonce": "${ownerNonce}", "pid": os.getpid(), "port": port,
        }
        with socket.socket() as contender:
            try:
                contender.bind(("127.0.0.1", port))
            except OSError as error:
                assert error.errno in {errno.EADDRINUSE, errno.EACCES}
            else:
                raise AssertionError("backend listener was released")
    server.uvicorn.Server.run = consume
    with server.bound_http_server() as port:
        assert not receipt.exists()
        instance = server.uvicorn.Server(server.uvicorn.Config(lambda scope: None))
        instance.run()
        assert claimed[0].getsockname()[1] == port
    assert claimed[0].fileno() == -1
    assert server.uvicorn.Server.run is consume
`);
  expect(result.status, result.stderr).toBe(0);
});

test.each(["uvicorn", "static"])(
  "serves native %s HTTP on the published child-owned endpoint",
  async (kind) => {
    const root = await mkdtemp(resolve(tmpdir(), "studio-backend-test-"));
    const receipt = resolve(root, "endpoint");
    const script = resolve(root, "app.py");
    await writeFile(resolve(root, "index.html"), "owned backend");
    await writeFile(
      script,
      `import uvicorn
async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"owned backend"})
uvicorn.run(app, lifespan="off", log_level="error")
`,
    );
    const args =
      kind === "uvicorn"
        ? [launcher, "python", script]
        : [resolve(appDirectory, "scripts/static-server.py"), "0", "--directory", root];
    const child = spawn(python, args, {
      cwd: root,
      env: {
        ...process.env,
        PYTHONSAFEPATH: "1",
        XDG_CONFIG_HOME: root,
        MARIMO_STUDIO_E2E_ENDPOINT_FILE: receipt,
        MARIMO_STUDIO_E2E_PROCESS_OWNER: ownerNonce,
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const closed = once(child, "close");
    let output = "";
    child.stdout.on("data", (data) => (output += String(data)));
    child.stderr.on("data", (data) => (output += String(data)));
    try {
      await expect
        .poll(() => readFile(receipt, "utf8").catch(() => ""), { timeout: 10_000 })
        .not.toBe("");
      const endpoint = JSON.parse(await readFile(receipt, "utf8"));
      expect(endpoint).toMatchObject({ ownerNonce, pid: child.pid });
      expect(endpoint.port).toBeGreaterThan(0);
      await expect
        .poll(
          async () => {
            if (child.exitCode !== null) throw new Error(output);
            return fetch(`http://127.0.0.1:${endpoint.port}`, {
              signal: AbortSignal.timeout(500),
            })
              .then((response) => response.text())
              .catch(() => "");
          },
          { timeout: 5_000 },
        )
        .toBe("owned backend");
    } finally {
      child.kill("SIGTERM");
      const forced = setTimeout(() => child.kill("SIGKILL"), 5_000);
      try {
        await closed;
      } finally {
        clearTimeout(forced);
        await rm(root, { force: true, recursive: true });
      }
    }
  },
);
