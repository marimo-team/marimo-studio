---
title: Identities and state
description: Canonical product terms, stable names, revisions, generations, runtime identities, and state mappings.
---

# Identities and state

Studio attaches every mutation, build, and presentation to
the state it observed. Names identify durable product objects. Revisions identify
content. Generations identify replaceable owners and incarnations.

## Product terms

| Term             | Contract                                                                                                                                                   |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Notebook         | Saved Marimo Python file that owns data, computation, controls, and reactive behavior                                                                      |
| View             | Stable name and route for one presentation of a notebook                                                                                                   |
| View project     | Directory containing `view.toml`, authored frontend source, and provider configuration for one view                                                        |
| Source document  | UTF-8 text file authorized by provider inspection or the Studio-owned `view.toml`                                                                          |
| Build input      | File or bounded directory included in the immutable snapshot used by a build                                                                               |
| View provider    | Installed Python extension that offers starters, inspects a view project, and builds browser files                                                         |
| Provider key     | Durable `distribution/registration` identity stored in `view.toml`                                                                                         |
| Starter          | Creation-time choice that produces initial view project files                                                                                              |
| Artifact         | Validated immutable browser file tree produced by one build profile                                                                                        |
| Presentation     | One artifact combined with notebook source, runtime configuration, projections, and browser session state                                                  |
| Preview          | Studio surface that renders the current development presentation                                                                                           |
| Python runtime   | Notebook execution in a server-side Marimo session. Its configuration ID is `server`                                                                       |
| Browser runtime  | Notebook execution in a browser worker through [WebAssembly](https://webassembly.org/) and [Pyodide](https://pyodide.org/). Its configuration ID is `wasm` |
| Prepared runtime | Browser rendering from verified outputs computed during export. Its static runtime ID is `zero-python`                                                     |

Source documents and build inputs are separate allowlists. A read-only lockfile
can affect a build without accepting Source writes. An editable guidance file
can remain outside the build input set when editing it should not rebuild the
artifact.

## Stable names

| Identity           | Format                                                                              | Lifetime                                          |
| ------------------ | ----------------------------------------------------------------------------------- | ------------------------------------------------- |
| View name          | Lowercase letter followed by lowercase letters, digits, or hyphens                  | Stable until the view is removed                  |
| Provider key       | Canonical distribution plus entry-point registration, such as `marimo-studio/react` | Preserved by Studio Source mutations for one view |
| Starter ID         | Provider key plus local starter key, such as `marimo-studio/react:reveal`           | Used during creation and not persisted            |
| Cell target        | Native cell name or Studio cell alias                                               | Stable while the notebook name or binding remains |
| Value selector     | Variable name plus permitted attribute and item steps                               | Resolves against the current notebook namespace   |
| Projection site ID | Lowercase artifact-local ID with at most 128 characters                             | Stable for one authored source site               |

## Content revisions

| Revision              | Identifies                                                                                   | Changes when                                                                           |
| --------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Source revision       | Exact UTF-8 source document content                                                          | The document bytes change. Public values use `sha256:<digest>`                         |
| Notebook revision     | Provider-visible static notebook record                                                      | Cell source, names, configuration, definitions, references, or dependency edges change |
| Project revision      | Complete normalized build-input snapshot plus provider provenance                            | A declared build input or provider build identity changes                              |
| Artifact revision     | Complete validated browser file tree and projection declarations                             | Any published artifact file or mount declaration changes                               |
| Presentation revision | Selected view, saved notebook and configuration, build profile, and artifact                 | Any input to the delivered presentation changes                                        |
| Projection revision   | Presentation projection targets, policy, runtime bindings, diagnostics, and runtime instance | Projection authorization or runtime binding state changes                              |

An artifact revision can remain current across repeated builds when the
validated browser file tree is byte-identical. Development and production
profiles can publish the same artifact revision while retaining separate build
attempt and publication state.

## Ownership generations

| Generation         | Identifies                                                               | Used by                                          |
| ------------------ | ------------------------------------------------------------------------ | ------------------------------------------------ |
| Catalog generation | Studio configuration plus the current set of named view incarnations     | Workspace mutation admission                     |
| View generation    | Durable owner of one name joined with the current view project directory | View write, build, export, and removal admission |

Both generations are opaque 64-character lowercase hexadecimal strings. Read
them from `status`, `view read --json`, or the Python handles that return them.
Do not construct or persist them as long-term identifiers.

`view write` checks the source revision, catalog generation, and view generation
immediately before commit. A failed check preserves the current file and
returns a conflict. Read the current source and retry from that state.

Removing a view terminates its view generation. Recreating the same name
creates a new view generation. Existing Python `View` handles remain bound to
the incarnation they observed.

## Runtime and browser identities

| Identity               | Scope                                                                                                                                  |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Runtime instance       | One mounted notebook runtime configuration                                                                                             |
| Runtime session ID     | One Python runtime session. Browser runtimes have no server session ID                                                                 |
| Browser client ID      | One connected Studio tab                                                                                                               |
| Presentation session   | One browser admission to a presentation revision                                                                                       |
| Projection instance ID | One active element in the browser [DOM](https://developer.mozilla.org/en-US/docs/Web/API/Document_Object_Model) at one projection site |

The browser document exposes its committed presentation revision as
`data-marimo-studio-revision` on `<html>`. Read it alongside
`data-marimo-studio-state` and assert the application's intended content and
behavior. An exact preview URL rejects a different presentation revision or
unbuilt or failed view source, including when a previous artifact is retained.

## Workspace state

`StudioOverview.state` and `marimo-studio status --json` use these values:

| State          | Meaning                                                                          |
| -------------- | -------------------------------------------------------------------------------- |
| `unconfigured` | The notebook has no Studio configuration                                         |
| `needs-view`   | Studio configuration exists and the default view project still needs creation    |
| `ready`        | The configured workspace has at least one valid view and its default view exists |

## Build freshness

`ViewInspection.freshness` and `view inspect --json` report development build
freshness:

| Freshness  | Current source        | Retained artifact | Meaning                                                                                     |
| ---------- | --------------------- | ----------------- | ------------------------------------------------------------------------------------------- |
| `current`  | Matches               | Present           | The development artifact was built from the current project revision                        |
| `stale`    | Newer or invalid      | Present           | Preview can retain the last successful artifact while source needs another successful build |
| `unbuilt`  | Present               | Absent            | Current source has no successful development artifact                                       |
| `building` | Build in progress     | Optional          | Studio is preparing a candidate from the current snapshot                                   |
| `failed`   | Latest attempt failed | Absent            | No successful development artifact is available                                             |

`ViewInspection.build` describes the retained successful artifact. It can remain
present when `freshness` is `stale`.

## Projection state

Projection hosts use `connecting`, `loading`, `stale`, `ready`, `missing`, and
`error`. See [Notebook result projections](projections.md#host-lifecycle) for
DOM attributes and events.

## Validation state

Validation levels are cumulative:

| Level     | Required evidence                                                                  |
| --------- | ---------------------------------------------------------------------------------- |
| `static`  | Saved notebook, configuration, view source, build contract, and projection targets |
| `runtime` | Static evidence plus one complete supervised notebook execution                    |

See [Errors and JSON](errors-and-json.md) for conflict codes and machine output.
