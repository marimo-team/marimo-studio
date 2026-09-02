# Security policy

## Supported versions

Security fixes target the latest published Marimo Studio release and the main
branch. The project will publish a broader support policy when it maintains more
than one release line.

## Report a vulnerability

Do not open a public issue with vulnerability details.

Use GitHub private vulnerability reporting for this repository. If private
reporting is unavailable, open a minimal issue asking the maintainers for a
private contact path. Do not include technical details, reproduction steps,
credentials, hostnames, logs, screenshots, notebook source, or view source in
that issue.

Include these details in the private report:

- Affected version or commit
- The affected boundary, such as source editing, provider execution, artifact
  delivery, notebook projections, Server runtime, WebAssembly runtime, static
  export, or agent validation
- Impact and minimal reproduction steps
- Any known mitigation

Identify the credential type and location when a committed or logged credential
is involved. Rotate the credential before sharing additional evidence.

## Trust boundaries

Studio view source and installed view providers execute code. Review their
source and dependencies before use. The [frontend provider
reference](docs/reference/provider-api.md) defines provider execution, and [Run
or export a view](docs/guide/run-and-share.md) defines browser and static-export
boundaries.

Runtime notebook inspection and validation execute notebook code in a supervised
child process. Process isolation gives Studio lifecycle, timeout, cancellation,
and cleanup ownership. It provides no operating-system security sandbox. The
notebook inherits the current working directory, environment variables, user
permissions, filesystem access, and network access. Run runtime inspection and
validation on trusted notebooks.
