import { expect, test } from "vite-plus/test";

import { standaloneViewUrl } from "../src/shared/standaloneViewUrl.ts";

test("a popout retains its source client while releasing frame lifecycle state", () => {
  const url = new URL(
    standaloneViewUrl(
      "/dashboard/?file=notebook.py&region=emea" +
        "&marimo_studio_client=client-123456789&marimo_studio_lifecycle=7" +
        "&marimo_studio_server=server-instance&session_id=s_abc123" +
        "&marimo_studio_resume=1",
    ),
  );

  expect(url.searchParams.get("file")).toBe("notebook.py");
  expect(url.searchParams.get("region")).toBe("emea");
  expect(url.searchParams.get("marimo_studio_client")).toBe("client-123456789");
  expect(url.searchParams.has("marimo_studio_lifecycle")).toBe(false);
  expect(url.searchParams.has("marimo_studio_server")).toBe(false);
  expect(url.searchParams.has("session_id")).toBe(false);
  expect(url.searchParams.has("marimo_studio_resume")).toBe(false);
});
