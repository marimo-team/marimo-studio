---
title: Limits
description: File, source, provider, projection, payload, output, and timeout limits enforced by Studio.
---

# Limits

Studio bounds source inspection, provider processes, build snapshots, browser
artifacts, projection requests, and validation waits. Limits apply before
publication or mutation commit unless the table names a browser boundary.

## Names and source documents

| Boundary                                              |           Limit | Failure or diagnostic                             |
| ----------------------------------------------------- | --------------: | ------------------------------------------------- |
| View name                                             | 240 UTF-8 bytes | `configuration-error` or an inline creation error |
| Source document                                       |          64 MiB | `source-too-large`                                |
| Source encoding                                       |           UTF-8 | `invalid-source-encoding`                         |
| Source documents returned by one provider inspection  |             256 | Provider conformance error                        |
| Provider path, title, summary, message, or hint field |    64 KiB UTF-8 | Provider conformance error                        |

View names must also fit the syntax and reserved-name rules in
[Configuration](configuration.md#view-projects). Source paths use forward
slashes relative to the view project root, reject `.` and `..` segments, and
resolve to regular files contained by the view project.

## Build inputs and artifacts

| Boundary                      | Files | Per file |   Total |
| ----------------------------- | ----: | -------: | ------: |
| Declared project build inputs | 4,096 |   64 MiB | 512 MiB |
| Published artifact            | 4,096 |  128 MiB |   1 GiB |

Studio rejects symlinks and path collisions that violate the contained project
or artifact contract. Artifact validation also rejects reserved routes, a
missing entry document, and a document without one `head`, one `body`, and one
`#app-shell`.

Static export combines the artifact with Studio runtime assets and notebook
public files. Prepared export adds verified output assets. Browser export
adds notebook source. Each copied tree is checked against the artifact file
budget before the staged directory can replace the destination.

## Projection declarations

| Boundary                                           |             Limit |
| -------------------------------------------------- | ----------------: |
| Mount declarations returned by provider inspection |               512 |
| Encoded mount declarations                         |             1 MiB |
| Finite cell targets on one mount                   |               256 |
| Finite output targets on one mount                 |               100 |
| Finite value targets on one mount                  |               100 |
| Projection target                                  | 4,096 UTF-8 bytes |
| Value selector path                                |          64 steps |
| Projection site ID                                 |    128 characters |

`allowed_targets=None` represents a dynamic mount and avoids enumerating its
target set during inspection. Runtime policy still applies to active instances
and unique targets. Prepared export requires finite targets on every mount.

## Active presentation projections

| Boundary                    |             Limit | Browser diagnostic               |
| --------------------------- | ----------------: | -------------------------------- |
| Active projection instances |               512 | `projection-instance-limit`      |
| Unique cell targets         |               256 | `projection-cell-target-limit`   |
| Unique output targets       |               100 | `projection-output-target-limit` |
| Unique value targets        |               100 | `projection-value-target-limit`  |
| Projection instance ID      |   256 UTF-8 bytes | Projection resolution error      |
| Projection target           | 4,096 UTF-8 bytes | Projection resolution error      |
| Value selector path         |          64 steps | Projection resolution error      |

One complete cell or rendered output can have one host per target. Duplicate
hosts enter an error state. Several `mo-value` hosts may share one value
target.

## Runtime payloads

| Boundary                                          |           Limit | Failure                                    |
| ------------------------------------------------- | --------------: | ------------------------------------------ |
| Encoded browser runtime configuration             |          16 MiB | `runtime-config-too-large`                 |
| One projected JSON value                          | 1,000,000 bytes | `value-too-large`                          |
| JSON values in one value read                     | 1,000,000 bytes | `response-too-large`                       |
| One projected Arrow value                         |          64 MiB | `value-too-large`                          |
| Arrow values in one value read                    |         128 MiB | `response-too-large`                       |
| Arrow values in one Browser runtime value read    |          64 MiB | `response-too-large`                       |
| One rendered output, and the outputs of a request | 1,000,000 bytes | `output-too-large` or `response-too-large` |
| One rendered output request set                   |   100 selectors | Capability or protocol error               |
| Browser client response                           | 5,000,000 bytes | Live request failure                       |

The Python and Browser runtimes enforce the value rows. A value read carries
the values that a view projects from one producer cell, and `marimo-studio
check` reads them the same way. Eager pandas, Polars, and PyArrow tables travel
as
[Arrow IPC](https://arrow.apache.org/docs/format/Columnar.html#serialization-and-interprocess-communication-ipc),
a columnar binary format. Every other value travels as JSON, so return a table
to project more than 1,000,000 bytes.

The Python runtime publishes Arrow values through marimo's shared memory. A
container's default 64 MiB `/dev/shm` holds about one large value, so start
containers with a larger `--shm-size`. A value that does not fit travels
inline, which takes longer to load.

The Browser runtime passes Arrow values from its worker as base64 text, so a
value read there carries at most 64 MiB of Arrow. A 60 MB value took about 8
seconds to appear in Chromium on a Linux workstation. `marimo-studio check`
applies the Python runtime budgets.

The Prepared runtime stores each value as a
[marimo-export](https://github.com/marimo-team/marimo-export) asset. One asset
holds at most 64 MiB, and one export holds at most 512 MiB of unique assets
across its prepared states.

Browser runtime configuration contains saved notebook source, projection
declarations, runtime bindings, and presentation settings. Prepared runtime
configuration contains the publication identity and manifest URL. Prefer
finite projection targets and reduce notebook source when a Browser record
reaches 16 MiB.

## Provider records

| Boundary                                  |                         Limit |
| ----------------------------------------- | ----------------------------: |
| Starters per provider                     |                           256 |
| Advertised documents per starter          |                           256 |
| Options in one view project               |                           256 |
| Cell targets consumed by one starter plan |                           256 |
| Provider inspection diagnostics           | 512 records and 1 MiB encoded |
| Provider build diagnostics                | 512 records and 1 MiB encoded |
| Encoded third-party operation request     |                       128 MiB |
| Encoded third-party operation result      |                        16 MiB |

Provider titles, summaries, option values, paths, diagnostics, starter files,
and notebook context also pass structural and byte validation. The [View
provider API](provider-api.md) defines the record responsibilities.

## Timeouts

| Operation                                                          |     Default |                                                       Accepted range or budget |
| ------------------------------------------------------------------ | ----------: | -----------------------------------------------------------------------------: |
| Runtime inspection and validation                                  |  60 seconds |                                                          0 through 300 seconds |
| Prepared export                                                    |  30 seconds |                                                              Positive duration |
| Provider runner command                                            | 120 seconds | Finite positive duration within the request's shared 120-second command budget |
| Third-party provider metadata, availability, and starter discovery |  10 seconds |                                             Fixed extension-operation deadline |

Runtime workers receive an additional 10-second shutdown allowance after the
requested runtime timeout. A timeout bounds waiting and cleanup ownership. It
does not restrict the operating-system authority of notebook or provider code.

## Browser message bounds

Navigation and public query synchronization accept at most 16 KiB of query
text and 8 KiB of URL fragment text. Studio validates messages between the
trusted presentation shell and the opaque-origin authored frame before changing
history or runtime state.
