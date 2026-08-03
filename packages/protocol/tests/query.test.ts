import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { publicNotebookQuery } from "../src/query.ts";

test("notebook query state preserves values and removes transport keys", () => {
  assert.deepEqual(
    publicNotebookQuery(
      "?region=emea&region=apac&empty=&file=analysis.py&session_id=s_123456&access_token=secret",
    ),
    "?region=emea&region=apac&empty=",
  );
  assert.deepEqual(publicNotebookQuery("?file=analysis.py&kiosk=true"), "");
});
