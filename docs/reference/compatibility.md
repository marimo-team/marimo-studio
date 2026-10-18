---
title: Compatibility and support
description: Supported Python, marimo, Deno, uv, browser, runtime, release, provider, deployment, and security contracts, and the upgrade from marimo-studio 0.3.
---

# Compatibility and support

The notebook-to-view workflow, projection elements, and last-successful build
behavior are supported product contracts. Before 1.0, CLI, Python, provider,
and saved configuration contracts may change between minor releases.

Add Studio to the notebook or project dependencies:

```toml
dependencies = ["marimo-studio"]
```

The `deno` and `typst` extras supply the toolchains listed under
[Supported environment](#supported-environment).

## Upgrade from 0.3

Studio 0.3.0 and earlier created views in
`__marimo__/studio/<notebook-stem>/`. The current release creates them in
`studio/<notebook-stem>/` and keeps build state in
`<state_root>/<view>/.artifacts/`, as
[Build state location](configuration.md#build-state-location) describes.

Studio keeps opening views in the 0.3 folder until you move them. That folder
is also the default `state_root`, so each view keeps its build state inside its
project. With `MARIMO_STUDIO_STATE_DIR`, `state_dir`, or `PYTHONPYCACHEPREFIX`
set, each view rebuilds once in the new location and leaves its old
`.artifacts/` folder unused.

To move the views, update the notebook's `marimo-studio` requirement to the
current release first, because Studio 0.3 looks for views only in the old
folder. Then stop Studio, move the folder to `studio/analysis`, which must not exist
yet, and delete the build state that moved with it:

```console
mkdir -p studio
mv __marimo__/studio/analysis studio/analysis
rm -rf studio/analysis/*/.artifacts
```

Each view rebuilds once in `state_root`. Other checkouts keep their own build
state in `__marimo__/studio/analysis/` after they pull the move. Delete that
folder there once the pull has removed the views from it.

A `view_root` configured under 0.3 keeps its views in place. Delete the
`.artifacts/` folder inside each view, and each view rebuilds once in
`state_root`.

Studio reports a configuration error when both folders contain views, or when
the build state folder of a view holds another view project. With the default
build state location, a configured `view_root` that leaves a view with the same
name in `__marimo__/studio/analysis/` causes the second error. Move the views
you keep into the folder Studio uses, then remove the old folder.

## Supported environment

| Component                                           | Contract                                                                                      |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Python                                              | 3.10 through 3.14                                                                             |
| marimo                                              | 0.25.1                                                                                        |
| [Deno](https://docs.deno.com/)                      | 2.9.5 or newer from the `deno` extra for React, Reveal.js, Svelte, and Notebook Kit authoring |
| [uv](https://docs.astral.sh/uv/)                    | Required when the CLI must prepare or re-enter a notebook or provider environment             |
| [pixi](https://pixi.prefix.dev/)                    | Optional. 0.80 or newer runs pixi workspaces, `--sandbox=pixi` notebooks, and their tools     |
| [Quarto](https://quarto.org/)                       | 1.9.38 or newer for the Quarto provider                                                       |
| [Typst](https://typst.app/)                         | The `typst` Python package 0.15 or newer, from the `typst` extra, for the Typst provider      |
| [Tectonic](https://tectonic-typesetting.github.io/) | 0.15 or newer for the LaTeX provider                                                          |
| Browser acceptance                                  | Current Chromium on Linux and Windows                                                         |

Windows builds and exports require [Win32 long paths](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation),
which let Python create staging files beyond the default 260-character path
limit. Enable `LongPathsEnabled=1` with administrator privileges, then restart
existing Studio and terminal processes.

The Python runtime can use the packages, files, databases, and credentials
available to its Python environment. The Browser runtime requires
[Pyodide](https://pyodide.org/)-compatible packages and data sources the visitor
can reach. [Run or export a view](../guide/run-and-share.md) defines those
runtime and delivery boundaries.

### Workspace storage

Studio keeps the notebook, its configuration, and every view project in the
notebook workspace. Each change publishes its result in one atomic step that
never replaces an existing name: an exclusive rename, or a hard link or empty
placeholder where the filesystem has no exclusive rename. Each change also
compares stable file identities, so the workspace must live on storage that
provides both:

| Platform        | Supported workspace storage                                                                                     |
| --------------- | --------------------------------------------------------------------------------------------------------------- |
| Linux and macOS | Local ext4, XFS, Btrfs, or APFS disks, NFSv3 and NFSv4 shares, and [gVisor](https://gvisor.dev/) sandbox mounts |
| Windows         | NTFS, ReFS, SMB shares, and OneDrive or SharePoint-synced folders                                               |
| WSL 2           | The Linux disk and NTFS drives mounted under `/mnt`                                                             |

Windows cloud-sync folders use data reparse points for online files. Studio
opens those entries through the cloud filter. Symlinks and junctions remain
outside the workspace contract.

Object-storage mounts such as [s3fs](https://github.com/s3fs-fuse/s3fs-fuse)
and [rclone](https://rclone.org/commands/rclone_mount/) rewrite file timestamps
when Studio reads a file and can drop file content when a directory is renamed.
exFAT and FAT32 drives renumber a file when it is renamed. Studio treats those
changes as concurrent edits and stops the operation. Copy the workspace to
supported storage before opening it, or let the hosting platform copy it into
the session and save it back afterwards.

## Runtime and delivery matrix

| Delivery             | Python `server` | Browser `wasm` | Prepared `zero-python` |
| -------------------- | --------------- | -------------- | ---------------------- |
| Studio Preview       | Supported       | Supported      | Supported in edit mode |
| Live run-mode server | Supported       | Supported      | Not applicable         |
| Static export        | Not applicable  | Supported      | Default                |

Static exports are HTTP directories.
[`view export`](cli.md#marimo-studio-view-export) lists their contents. A
Browser export runs saved notebook source through Pyodide. Imported packages,
remote data, fonts, maps, and other browser resources keep their own network
and cross-origin requirements.

## Deployment boundary

`create_asgi_app()` and `marimo_studio.asgi:app` return a run-mode marimo
[ASGI](https://asgi.readthedocs.io/en/latest/) application with Studio
middleware and owned lifespan cleanup. ASGI is the standard interface between
asynchronous Python web applications and servers. The hosting stack owns
[TLS](https://developer.mozilla.org/en-US/docs/Glossary/TLS) connection
encryption, proxy headers, process supervision, resource limits, and network
exposure. Forward the application lifespan so Studio can close notebook
sessions and background tasks during shutdown.

marimo authentication supplies `read` and `edit` scopes to Studio routes.
Source mutations also require the marimo server token. Run-mode presentations
use read access. Keep authentication enabled when a deployment can execute
Python code or reach private files, services, or credentials.

Provider-authored pages run inside a sandboxed
[iframe](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe),
an embedded browser document, with an opaque origin. The sandbox permits
scripts, forms, downloads, modals, pointer lock, and popups. It withholds
same-origin access and top-level navigation. Studio validates navigation,
query, replay, and readiness messages at the parent boundary.

Set `MARIMO_STUDIO_TRUSTED_SERVER_RUNTIME=1` for a trusted single-tenant
deployment that needs Server runtime documents to share the authenticated host
origin. A marimohub session with proxy exposure enables it when the variable is
unset, because the hub already serves notebook output on its own origin.
[Process settings](configuration.md#process-settings) defines its scope.
Browser and Prepared runtimes keep opaque-origin isolation.

## Third-party view providers

Declare `marimo-studio` as a dependency bounded to the minor line the provider
has tested, such as `marimo-studio>=0.4,<0.5`. Test the provider against each
Studio minor release it supports with
[`check_provider()`](provider-api.md#check-provider).

The [View provider API](provider-api.md) defines process execution,
permissions, cancellation, build inputs, output validation, and conformance
limits. Provider packages and their child commands run with the current user's
filesystem, environment, and network authority.

## Support and security

Security fixes target the latest published release and the `main` branch. Use
the latest Studio release when reporting a bug.

- Open public bug reports and support requests in [GitHub
  Issues](https://github.com/marimo-team/marimo-studio/issues).
- Follow the [troubleshooting guide](../guide/troubleshooting.md) to collect
  redacted diagnostic output.
- Report suspected vulnerabilities through the private path in the [security
  policy](https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md).
