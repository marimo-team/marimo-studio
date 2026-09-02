"""Run each third-party provider call in an owned child process.

The host writes one bounded request, starts a worker, validates its response,
and owns the call's deadline, captured output, cancellation, and descendant
cleanup. Inspection and build requests still receive Studio's bounded command
runner and use the same request and result shapes as bundled providers.

The worker keeps the current user's filesystem permissions. Cancellation
terminates the process tree, so provider cleanup code cannot be assumed to run
before the operation ends.
"""
