"""Protect workspace and artifact files during concurrent changes.

Studio reads source, writes manifests, publishes artifacts, and rolls back
multi-file operations while editors or other processes may change nearby
paths. This package holds the containing directory open, rejects symbolic links
and Windows reparse points, limits recursive work, and replaces complete files
atomically.

Basic writes replace a complete file under the stable parent that Studio
opened. Revision-aware Source saves additionally compare the file the caller
read, and multi-file workspace transactions retain enough identity to restore
or quarantine their own changes after failure.
"""
