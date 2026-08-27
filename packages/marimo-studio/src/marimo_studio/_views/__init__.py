"""Manage named frontend projects attached to one notebook.

This package creates views from provider starters, discovers the documents
shown in Source, performs revision-aware reads and saves, builds immutable
browser artifacts, resolves permitted notebook targets, migrates older
projects, and removes views through recoverable workspace transactions.

Providers describe and build their frontend format. Studio controls which
files may be edited, captures the exact build inputs, and publishes output only
while those inputs remain current. Conflicting saves preserve newer edits,
failed builds preserve the last publication, and removal keeps the remaining
workspace and default view valid.
"""
