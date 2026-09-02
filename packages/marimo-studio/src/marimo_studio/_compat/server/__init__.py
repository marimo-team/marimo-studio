"""Connect Studio's server features to the pinned Marimo server.

These adapters let Studio reuse Marimo's editor, live sessions, notebook save
path, session replay, control synchronization, usage reporting, and
programmatic applications. They keep the notebook and session association
explicit so a preview or agent operation reaches the editor session that owns
its current notebook state.

The application that creates these integrations also owns their lifetime.
Closing the application detaches patches, listeners, replay registrations,
session routes, and other process-wide hooks installed on its behalf.
"""
