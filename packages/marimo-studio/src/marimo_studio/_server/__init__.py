"""Mount Studio's browser and agent services beside Marimo's ASGI server.

Marimo continues to own notebook execution, the native editor, sessions,
WebSockets, and virtual files. Studio adds an authoring workspace, named view
URLs, source editing, immutable artifacts, runtime configuration, notebook
projections, live development events, and agent endpoints. Routes outside that
surface continue to the original Marimo application.

Each resolved notebook gets one scope that owns its presentation, source
monitoring, connected browsers, and agent operations. Closing that scope drains
the background work and resources created for the notebook.
"""
