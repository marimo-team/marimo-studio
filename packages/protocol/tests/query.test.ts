import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { notebookQueryValues, notebookRouteQuery, publicNotebookQuery } from "../src/query.ts";

test("notebook query state preserves public values and removes transport keys", () => {
  const query = publicNotebookQuery(
    "?region=emea&region=apac&empty=&file=analysis.py&session_id=s_123456&access_token=secret&runtime=wasm",
  );

  assert.deepEqual(query, "?region=emea&region=apac&empty=");
  assert.deepEqual(notebookQueryValues(query), {
    region: ["emea", "apac"],
    empty: "",
  });
  assert.deepEqual(publicNotebookQuery("?file=analysis.py&kiosk=true"), "");
  assert.equal(
    notebookRouteQuery("?region=emea&file=reports%2Fanalysis.py&session_id=session"),
    "?file=reports%2Fanalysis.py",
  );
});
