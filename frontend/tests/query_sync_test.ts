import { assertEquals } from "@std/assert";

import { publicNotebookQuery } from "../src/query-sync.ts";

Deno.test("notebook query state preserves values and removes transport keys", () => {
  assertEquals(
    publicNotebookQuery(
      "?region=emea&region=apac&empty=&file=analysis.py&session_id=s_123456&access_token=secret",
    ),
    "?region=emea&region=apac&empty=",
  );
  assertEquals(publicNotebookQuery("?file=analysis.py&kiosk=true"), "");
});
