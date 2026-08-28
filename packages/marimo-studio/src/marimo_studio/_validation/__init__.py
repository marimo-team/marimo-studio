"""Assess a view from saved source through the page a browser rendered.

Validation advances in stages. Static checks inspect notebook and frontend
source first. Runtime checks start the complete reactive notebook in an
isolated process and inspect the selected cells, outputs, and values. Browser
checks confirm that the intended page, runtime, and mounted results reached a
ready or failed state in the selected Studio browser while recording the public
query state that browser observed.

The validation sequence captures source and page revisions, rechecks source
stability, and requires browser evidence to match the captured page. Concurrent
edits therefore become an explicit stale-source failure. Reports use common
check codes and actionable issues. A successful result always describes the
requested source, runtime, and browser evidence.
"""
