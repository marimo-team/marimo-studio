import {
  parseHostSessionConfig,
  type HostSessionConfig,
} from "@marimo-studio/protocol/host-session";
import { describe, expect, it } from "vite-plus/test";

import { hostSessionHandoffUrl, studioHostUrl } from "../src/app/host-session.ts";

const capability = "a".repeat(64);
const config = (transition: HostSessionConfig["transition"]): HostSessionConfig => ({
  capability,
  handoff: "marimo_studio_handoff",
  resume: "marimo_studio_resume",
  schema: 1,
  session: "s_123456",
  transition,
});

describe("host session navigation", () => {
  it("connects the issued consumer with its signed handoff", () => {
    const target = hostSessionHandoffUrl(
      config("native"),
      "https://example.test/?region=emea&session_id=s_654321&marimo_studio_resume=1",
    );

    expect(target.searchParams.get("session_id")).toBe("s_123456");
    expect(target.searchParams.get("marimo_studio_handoff")).toBe(capability);
    expect(target.searchParams.get("region")).toBe("emea");
    expect(target.searchParams.has("marimo_studio_resume")).toBe(false);
  });

  it("completes the issued native handoff", () => {
    const target = hostSessionHandoffUrl(
      config("complete"),
      "https://example.test/?marimo_studio_resume=1&marimo_studio_handoff=old",
    );

    expect(target.search).toBe("?session_id=s_123456");
  });

  it("keeps the public Studio location after connection", () => {
    const target = studioHostUrl(
      config("complete"),
      "https://example.test/studio?region=emea&session_id=s_old&marimo_studio_resume=1&marimo_studio_handoff=old",
    );

    expect(target.search).toBe("?region=emea");
  });

  it("rejects unknown transitions", () => {
    expect(() => parseHostSessionConfig({ ...config("native"), transition: "unknown" })).toThrow();
  });
});
