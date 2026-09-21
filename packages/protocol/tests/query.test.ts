import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { notebookQueryValues, notebookRouteQuery, publicNotebookQuery } from "../src/query.ts";

test("notebook query state preserves public values and removes transport keys", () => {
  const privateQuery = [
    "access_token=secret",
    "file=analysis.py",
    "kiosk=true",
    "marimo_studio_client=client-123",
    "marimo_studio_connection=2",
    "marimo_studio_editor=editor-capability",
    "marimo_studio_events=events-capability",
    "marimo_studio_lifecycle=7",
    "marimo_studio_query_operation=query-1",
    "marimo_studio_renewal=renewal-capability",
    "marimo_studio_resume=1",
    "marimo_studio_revision=presentation-checkpoint",
    "marimo_studio_server=server-instance",
    "marimo_studio_view=dashboard",
    "refresh_token=refresh-secret",
    "runtime=wasm",
    "session_id=s_123456",
  ].join("&");
  const query = publicNotebookQuery(`?region=emea&region=apac&empty=&${privateQuery}`);

  assert.deepEqual(query, "?region=emea&region=apac&empty=");
  assert.deepEqual(notebookQueryValues(query), {
    region: ["emea", "apac"],
    empty: "",
  });
  assert.equal(
    notebookRouteQuery("?region=emea&file=reports%2Fanalysis.py&session_id=session"),
    "?file=reports%2Fanalysis.py",
  );
});
