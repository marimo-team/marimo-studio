"""Timeout budgets for view requests to a running Studio server."""

VIEW_ACTIVATION_TIMEOUT = 120.0
VIEW_ACTIVATION_HTTP_TIMEOUT = VIEW_ACTIVATION_TIMEOUT + 5.0
# Removal and rename first drain the server's builds and presentations for the
# retired view name.
VIEW_RETIREMENT_HTTP_TIMEOUT = 60.0
