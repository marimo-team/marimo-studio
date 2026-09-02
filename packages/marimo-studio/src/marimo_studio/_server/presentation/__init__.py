"""Serve one coherent view page and its notebook interactions.

A presentation combines one immutable browser artifact with the saved notebook
and the map from authored hosts to notebook results. The page keeps that exact
combination while it loads assets, reads values, renders native output, updates
query state, or reports browser evidence. A failed later build leaves the last
working presentation available when one exists.

Provider-authored HTML runs inside a sandboxed presentation frame. Signed URLs
grant that frame the narrow access needed for its view, presentation revision,
artifact revision, runtime, and session. Requests from an older presentation,
another view, or a replaced session are rejected before they reach the live
notebook.
"""
