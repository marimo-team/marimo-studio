"""Own verified browser files from build input through final use.

Studio builds a view from an immutable copy of the files declared by its
provider. Provider output becomes a published artifact only after Studio
validates the complete file tree and confirms that the authored source is
still the source that started the build.

A failed or superseded build leaves the last successful publication available.
Leases retain the exact revision used by a presentation, browser response, or
export until that work finishes, then unreferenced revisions can be removed.
"""
