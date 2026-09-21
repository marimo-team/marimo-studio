"""Validate saved source and isolated notebook execution.

Static checks inspect notebook and view source. Runtime checks execute the
complete reactive notebook in an isolated process and inspect its projected
cells, outputs, and values. Each stage rechecks source identity so concurrent
edits produce an explicit stale-source failure.

Browser rendering and interaction are inspected independently at the view URL
with the developer's browser tools.
"""
