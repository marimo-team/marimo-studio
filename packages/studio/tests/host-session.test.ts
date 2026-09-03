import {
  parseHostSessionConfig,
  type HostSessionConfig,
} from "@marimo-studio/protocol/host-session";
import { describe, expect, it } from "vite-plus/test";

import {
  hostSessionHandoffUrl,
  resolveHostSessionStorage,
  studioHostUrl,
} from "../src/app/host-session.ts";

const capability = "a".repeat(64);
const retainedCapability = "b".repeat(64);

const config = (transition: HostSessionConfig["transition"]): HostSessionConfig => ({
  capability,
  handoff: "marimo_studio_handoff",
  key: "host-session",
  resume: "marimo_studio_resume",
  schema: 1,
  session: "s_123456",
  transition,
});

const storage = (initial: string | null = null) => {
  let value = initial;
  return {
    getItem: () => value,
    setItem: (_key: string, next: string) => {
      value = next;
    },
    value: () => value,
  };
};

describe("host session navigation", () => {
  it("resumes a retained Studio session", () => {
    const sessionStorage = storage(
      JSON.stringify({ schema: 1, session: "s_654321", capability: retainedCapability }),
    );

    const target = hostSessionHandoffUrl(
      config("studio"),
      "https://example.test/studio?region=emea",
      sessionStorage,
    );

    expect(target.searchParams.get("session_id")).toBe("s_654321");
    expect(target.searchParams.get("marimo_studio_resume")).toBe("1");
    expect(target.searchParams.has("marimo_studio_handoff")).toBe(false);
  });

  it("resets invalid retained state to the issued ticket", () => {
    const sessionStorage = storage(JSON.stringify({ session: "wrong", capability: "wrong" }));

    const target = hostSessionHandoffUrl(
      config("native"),
      "https://example.test/?marimo_studio_resume=1",
      sessionStorage,
    );

    expect(target.searchParams.get("session_id")).toBe("s_123456");
    expect(target.searchParams.get("marimo_studio_handoff")).toBe(capability);
    expect(target.searchParams.has("marimo_studio_resume")).toBe(false);
    expect(sessionStorage.value()).toBe(
      JSON.stringify({ capability, schema: 1, session: "s_123456" }),
    );
  });

  it.each([
    {
      transition: "native" as const,
      handoff: retainedCapability,
      session: "s_654321",
    },
    {
      transition: "complete" as const,
      handoff: null,
      session: "s_654321",
    },
    {
      transition: "reset" as const,
      handoff: capability,
      session: "s_123456",
    },
  ])("applies the $transition private-query policy", ({ transition, handoff, session }) => {
    const sessionStorage = storage(
      JSON.stringify({ schema: 1, session: "s_654321", capability: retainedCapability }),
    );

    const target = hostSessionHandoffUrl(
      config(transition),
      "https://example.test/?marimo_studio_resume=1&marimo_studio_handoff=old",
      sessionStorage,
    );

    expect(target.searchParams.get("session_id")).toBe(session);
    expect(target.searchParams.get("marimo_studio_handoff")).toBe(handoff);
    expect(target.searchParams.has("marimo_studio_resume")).toBe(false);
  });

  it("continues with the issued ticket when session storage is denied", () => {
    const deniedStorage = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };

    const target = hostSessionHandoffUrl(config("native"), "https://example.test/", deniedStorage);

    expect(target.searchParams.get("session_id")).toBe("s_123456");
    expect(target.searchParams.get("marimo_studio_handoff")).toBe(capability);
  });

  it("continues when the browser denies access to its session storage", () => {
    const sessionStorage = resolveHostSessionStorage(() => {
      throw new Error("denied");
    });

    const target = hostSessionHandoffUrl(config("native"), "https://example.test/", sessionStorage);

    expect(target.searchParams.get("session_id")).toBe("s_123456");
    expect(target.searchParams.get("marimo_studio_handoff")).toBe(capability);
  });

  it("stores the Studio ticket and removes transport authority", () => {
    const sessionStorage = storage();

    const target = studioHostUrl(
      config("complete"),
      "https://example.test/studio?session_id=s_old&marimo_studio_resume=1&marimo_studio_handoff=old",
      sessionStorage,
    );

    expect(target.search).toBe("");
    expect(sessionStorage.value()).toBe(
      JSON.stringify({ capability, schema: 1, session: "s_123456" }),
    );
  });

  it("rejects unknown transitions", () => {
    expect(() => parseHostSessionConfig({ ...config("native"), transition: "unknown" })).toThrow();
  });
});
