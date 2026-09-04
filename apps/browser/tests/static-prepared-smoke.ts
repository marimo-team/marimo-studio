import { openPreparedPublication } from "@marimo-team/marimo-export/prepared";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import {
  parseStudioPreparedManifest,
  parseZeroPythonRuntimeData,
  validateStudioPreparedManifest,
} from "../src/zero-python/metadata.ts";
import { staticSmokeFetch, staticSmokeUrl } from "./static-prepared-smoke-support.ts";

const [configSource, manifestSource] = process.argv.slice(2);
if (configSource === undefined || manifestSource === undefined) {
  throw new Error("Pass the static runtime config and prepared manifest paths.");
}

// SAFETY: The runtime fields are checked before use.
const config = JSON.parse(await readFile(configSource, "utf8")) as {
  readonly runtime?: {
    readonly id?: unknown;
    readonly data?: unknown;
  };
};
if (config.runtime?.id !== "zero-python") {
  throw new Error("The static runtime config must select Zero-Python.");
}
const runtime = parseZeroPythonRuntimeData(config.runtime.data);
const metadata = parseStudioPreparedManifest(JSON.parse(await readFile(manifestSource, "utf8")));
if (runtime.planDigest !== metadata.planDigest) {
  throw new Error("The runtime and prepared manifest plan digests differ.");
}

const siteRoot = resolve(dirname(configSource), "../../..");

const publication = await openPreparedPublication(
  metadata.prepared,
  staticSmokeUrl(siteRoot, manifestSource),
  { fetch: staticSmokeFetch(siteRoot) },
);
validateStudioPreparedManifest(
  metadata,
  {
    view: metadata.view,
    planDigest: runtime.planDigest,
  },
  publication.notebookExport,
  metadata.prepared.instance,
);
const verification = await publication.notebookExport.verify();

process.stdout.write(
  `${JSON.stringify({
    runtime,
    prepared: {
      schema: metadata.prepared.schema,
      instance: metadata.prepared.instance,
      stateFingerprint: publication.state.fingerprint,
    },
    verification,
  })}\n`,
);
