"""Keep provider and validation processes bounded and fully cleaned up.

Provider commands must run inside the project root supplied by their request.
Provider commands and isolated validation runs have bounded time and captured
output, own their descendant processes, and carry cancellation from the browser
or server to the complete process tree on POSIX and Windows.

Cancellation returns after the owned work has stopped. Cleanup failures remain
visible because a surviving compiler, kernel, or worker can interfere with a
later build, validation run, view deletion, or server shutdown.
"""
