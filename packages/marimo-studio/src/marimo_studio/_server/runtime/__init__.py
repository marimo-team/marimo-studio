"""Select the execution environment that supplies notebook results to a view.

The Server runtime connects a page to an existing Marimo Python session. The
WebAssembly runtime packages saved notebook source for execution in a browser
worker. Workspace configuration determines which choices a view may use, and
an unavailable or disallowed selection fails explicitly.

Every returned browser configuration stays tied to the exact page, notebook
source, and permitted projections that produced it. Server configuration also
binds the current Marimo session, while WebAssembly executes in its browser
worker without a native session.
"""
