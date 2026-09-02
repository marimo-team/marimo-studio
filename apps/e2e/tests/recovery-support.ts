import { e2eNetwork } from "../scripts/network.mjs";
import { workspaceNotebookPath } from "./fixture.ts";
import { startNotebookServer } from "./notebook-server.ts";

const recoveryServerPort = e2eNetwork.main.recovery.port;

export const runServerUrl = e2eNetwork.main.recovery.origin;
export const runServerToken = "recovery-e2e-token";
export const editServerUrl = runServerUrl;

export const startRunServer = () =>
  startNotebookServer({
    command: "run",
    target: workspaceNotebookPath,
    port: recoveryServerPort,
    authentication: ["--token-password", runServerToken],
  });

export const startEditServer = () =>
  startNotebookServer({
    command: "edit",
    target: workspaceNotebookPath,
    port: recoveryServerPort,
    authentication: ["--no-token"],
  });
