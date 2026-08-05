const AUTHORED_SCRIPT = "script:not([data-marimo-studio-runtime]):not([data-marimo-studio-dev])";
const EXECUTABLE_TYPES = new Set([
  "",
  "application/ecmascript",
  "application/javascript",
  "application/x-ecmascript",
  "application/x-javascript",
  "importmap",
  "module",
  "speculationrules",
  "text/ecmascript",
  "text/javascript",
  "text/javascript1.0",
  "text/javascript1.1",
  "text/javascript1.2",
  "text/javascript1.3",
  "text/javascript1.4",
  "text/javascript1.5",
  "text/jscript",
  "text/livescript",
  "text/x-ecmascript",
  "text/x-javascript",
]);

const executes = (script: HTMLScriptElement): boolean =>
  EXECUTABLE_TYPES.has(script.type.trim().toLowerCase());

export const hasAuthoredScripts = (root: ParentNode): boolean =>
  Array.from(root.querySelectorAll<HTMLScriptElement>(AUTHORED_SCRIPT)).some(
    (script) => !script.closest("[data-marimo-cell-output]") && executes(script),
  );

export const requiresDocumentReload = (current: Document, next: Document): boolean =>
  hasAuthoredScripts(current) || hasAuthoredScripts(next);
