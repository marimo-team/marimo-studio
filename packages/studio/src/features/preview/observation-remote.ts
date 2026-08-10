import type { BrowserObservation } from "@marimo-studio/protocol/browser-observations";

import { appendUrlPath } from "@marimo-studio/protocol/url";

export type RecordBrowserObservation = (observation: BrowserObservation) => Promise<void>;

export const createBrowserObservationRemote =
  (supportUrl: (view: string) => string, serverToken: string): RecordBrowserObservation =>
  async (observation) => {
    const response = await fetch(
      appendUrlPath(supportUrl(observation.view), "observation", globalThis.location.href),
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "Marimo-Server-Token": serverToken,
        },
        body: JSON.stringify(observation),
      },
    );
    if (!response.ok) {
      throw new Error(`Browser observation could not be recorded (${response.status})`);
    }
  };
