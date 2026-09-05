---
title: Errors and JSON
description: Stable JSON result, JSON Lines progress and diagnostics, HTTP error, Python exception, and exit-status contracts.
---

# Errors and JSON

`--json` gives commands separate result and diagnostic channels:

- Standard output contains one JSON result after a successful operation.
- Standard error contains one JSON object per progress or diagnostic line.
- The process exit status identifies the failure category.

Keep the streams separate when another program reads the result.

```sh
marimo-studio status --target analysis.py --json \
  >status.json 2>diagnostics.jsonl
```

Every top-level result record has `schema: 1`. The command-specific result
shape matches the `to_dict()` contract of its Python record. See [Python
API](python-api.md#public-records) for record fields.

## Diagnostic events

[JSON Lines](https://jsonlines.org/) stores one JSON object on each line, so a
caller can process diagnostics as they arrive. One event has this shape:

```json
{
  "schema": 1,
  "event": "diagnostic",
  "command": "view create",
  "severity": "info",
  "code": "next-command",
  "message": "uvx --with marimo-studio==0.1.0 marimo edit analysis.py --sandbox",
  "details": {
    "action": "edit"
  }
}
```

| Field       | Type                          | Contract                                                              |
| ----------- | ----------------------------- | --------------------------------------------------------------------- |
| `schema`    | integer                       | `1`                                                                   |
| `event`     | string                        | `diagnostic`                                                          |
| `command`   | string or `null`              | Parsed command path, such as `view build`                             |
| `severity`  | `info`, `warning`, or `error` | Diagnostic severity                                                   |
| `code`      | string                        | Stable machine-readable category                                      |
| `message`   | string                        | Human-readable description                                            |
| `exit_code` | integer, optional             | Process exit status associated with an error                          |
| `status`    | string, optional              | Operation-specific state                                              |
| `details`   | object, optional              | Structured paths, revisions, hints, recovery files, and other context |

Output from a provider or child process that is not a valid trusted diagnostic
event becomes a bounded `process-output` warning. Studio retains at most the
last 16,384 characters of that text and reports omitted character counts in
`details`.

## Progress events

Long-running static preflight and export commands stream progress on standard
error. One JSON Lines record has this shape:

```json
{
  "schema": 1,
  "event": "progress",
  "command": "view export",
  "progress": {
    "view": "dashboard",
    "runtime": "zero-python",
    "source": "marimo-export",
    "event": {
      "kind": "state_finished",
      "completed": 3,
      "total": 12,
      "state": "reviewed",
      "cache": {
        "authored_hits": 4,
        "authored_misses": 1,
        "projection_hits": 2,
        "projection_misses": 0
      },
      "elapsed_seconds": 0.42,
      "message": null
    }
  }
}
```

Consumers may render, retain, or discard these records. The successful terminal
result remains one JSON object on standard output. A re-entered notebook
environment relays the same progress records instead of folding them into
process-output warnings.

## Expected command failures

An expected `MarimoStudioError` produces one error diagnostic with its stable
`code`, message, exit status, optional `hint`, optional `transient: true`, and
`diagnostic_details()` fields.

Click argument errors use code `usage-error` and exit status `2`. An interrupted
confirmation or command uses code `interrupted` and exit status `130`.

|  Exit | Category                                                       |
| ----: | -------------------------------------------------------------- |
|   `0` | Operation completed                                            |
|   `1` | Validation or a named provider availability check failed       |
|   `2` | Arguments or capability input are invalid                      |
|   `3` | Configuration, source, build, export, or mutation state failed |
|   `4` | Cell alias binding failed                                      |
|   `5` | A live Studio request failed                                   |
|   `6` | Studio and Marimo protocol contracts disagree                  |
|   `7` | The target Python environment could not be prepared            |
| `130` | The command was interrupted                                    |

## Python error contract

Catch `MarimoStudioError` for expected failures:

```python
from marimo_studio.errors import MarimoStudioError

try:
    await view.build()
except MarimoStudioError as error:
    print(error.code, error.exit_code, error.transient)
    print(error.diagnostic_details())
```

Every expected error exposes:

| Attribute or method    | Contract                                        |
| ---------------------- | ----------------------------------------------- |
| `code`                 | Stable machine-readable category                |
| `exit_code`            | CLI exit status                                 |
| `status_code`          | HTTP status used by Studio routes               |
| `transient`            | Whether a fresh read or later retry may succeed |
| `public_hint`          | Repair action suitable for a public surface     |
| `public_message()`     | Message safe for browser routes                 |
| `diagnostic_details()` | JSON-compatible repair context                  |

### Public error classes

| Class                              | Code                                                                                                                         | Exit |                   HTTP | Recovery contract                                                    |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ---: | ---------------------: | -------------------------------------------------------------------- |
| `MarimoStudioError`                | `marimo-studio-error`                                                                                                        |  `3` |                  `500` | Base class                                                           |
| `ConfigurationError`               | `configuration-error`                                                                                                        |  `3` |                  `500` | Fix saved configuration or source                                    |
| `NotebookSourceError`              | `notebook-source-error`                                                                                                      |  `3` |                  `500` | Fix and save the highlighted Marimo cell                             |
| `ViewProjectError`                 | `view-project-error`                                                                                                         |  `3` |                  `500` | Fix the source-located provider diagnostic and rebuild               |
| `BindingError`                     | `binding-error`                                                                                                              |  `4` |                  `500` | Select a valid cell or alias                                         |
| `ProtocolError`                    | `protocol-error`                                                                                                             |  `6` |                  `500` | Align installed Studio and Marimo versions                           |
| `CapabilityInputError`             | Supplied by the caller                                                                                                       |  `2` |                  `400` | Fix the field named in `details.field`                               |
| `RuntimeTimeoutError`              | `runtime-timeout`                                                                                                            |  `3` |                  `504` | Fix the blocking notebook operation or increase the timeout          |
| `AgentRequestError`                | Supplied by the server                                                                                                       |  `5` | Supplied by the server | Use returned details and retry classification                        |
| `DependencyError`                  | `dependency-error`                                                                                                           |  `7` |                  `500` | Repair target Python metadata or environment preparation             |
| `StaticExportError`                | `static-export-error`, `static-delivery-preflight-failed`, or a marimo-export `destination_*` or `export_commit_failed` code |  `3` |                  `500` | Repair the source, reference, or destination named by the diagnostic |
| `PublicationError`                 | `zero-python-publication-error`, `zero-python-projection-*`, or the originating marimo-export code                           |  `3` |                  `409` | Repair the projected result or select another static runtime         |
| `PublicationUnavailableError`      | `zero-python-publication-unavailable`                                                                                        |  `3` |                  `409` | Prepare the selected Zero-Python view and retry                      |
| `PublicationLimitError`            | `zero-python-state-limit`                                                                                                    |  `3` |                  `413` | Reduce the prepared state space                                      |
| `RuntimeSelectionError`            | `runtime-unavailable`                                                                                                        |  `3` |                  `400` | Select a runtime listed by the workspace                             |
| `RuntimeConfigTooLargeError`       | `runtime-config-too-large`                                                                                                   |  `3` |                  `413` | Bound projection targets or reduce notebook source                   |
| `SourceNotFoundError`              | `source-not-found`                                                                                                           |  `3` |                  `404` | Read the current Source catalog and select an authorized path        |
| `SourceEncodingError`              | `invalid-source-encoding`                                                                                                    |  `3` |                  `400` | Save the source document as UTF-8                                    |
| `SourceValidationError`            | `invalid-source-content`                                                                                                     |  `3` |                  `400` | Repair the affected source or manifest contract                      |
| `SourceTooLargeError`              | `source-too-large`                                                                                                           |  `3` |                  `413` | Reduce the source document size                                      |
| `SourceConflictError`              | `source-conflict`                                                                                                            |  `3` |                  `412` | Read the current revision, merge, and retry                          |
| `ViewNotFoundError`                | `view-not-found`                                                                                                             |  `3` |                  `404` | Choose an entry from `available_views`                               |
| `ProviderNotFoundError`            | `provider-not-found`                                                                                                         |  `3` |                  `404` | Install or choose an entry from `available_providers`                |
| `ViewExistsError`                  | `view-exists`                                                                                                                |  `3` |                  `409` | Choose another name or remove the existing view first                |
| `ViewGenerationConflictError`      | `view-generation-conflict`                                                                                                   |  `3` |                  `409` | Reopen the workspace and reacquire the view                          |
| `WorkspaceGenerationConflictError` | `workspace-generation-conflict`                                                                                              |  `3` |                  `409` | Open the workspace again                                             |
| `WorkspaceMutationError`           | `workspace-mutation-incomplete`                                                                                              |  `3` |                  `409` | Inspect `recovery` and reload before retrying                        |
| `ViewDeletionError`                | `view-deletion-error`                                                                                                        |  `3` |                  `500` | Inspect `cleanup` or `recovery` before another mutation              |
| `ViewInUseError`                   | `view-in-use`                                                                                                                |  `3` |                  `409` | Close artifact readers and retry removal                             |
| `LastViewError`                    | `last-view`                                                                                                                  |  `3` |                  `409` | Keep one configured view                                             |

Generation and incomplete-mutation errors marked `transient` require a fresh
read before retry. `AgentRequestError` can also carry a server-supplied retry
classification.

## HTTP error responses

Studio routes encode expected errors as JSON:

```json
{
  "error": "source-conflict",
  "message": "index.html changed on disk.",
  "revision": "sha256:..."
}
```

The response status equals `error.status_code`. `Marimo-Studio-Error` repeats
the code in a response header, and expected error responses use
`Cache-Control: no-store`. An available hint appears as `hint`. A retryable
failure includes `transient: true`.

Authentication failures use route-owned codes such as
`authentication-required`, `edit-access-required`, `missing-server-token`, and
`invalid-server-token`.
