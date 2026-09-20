import { e2eNetwork } from "../scripts/network.mjs";
import { workspaceNotebookPath } from "./fixture.ts";
import { startNotebookServer } from "./notebook-server.ts";

export const runServerUrl = () => e2eNetwork.main.recovery.origin;
export const runServerToken = "recovery-e2e-token";
export const editServerUrl = runServerUrl;

export const startRunServer = () =>
  startNotebookServer({
    command: "run",
    target: workspaceNotebookPath,
    endpoint: e2eNetwork.main.recovery,
    authentication: ["--token-password", runServerToken],
  });

export const startEditServer = () =>
  startNotebookServer({
    command: "edit",
    target: workspaceNotebookPath,
    endpoint: e2eNetwork.main.recovery,
    authentication: ["--no-token"],
  });
