"""Deliver validated view publications to live and static browsers.

Live pages and static exports use the same immutable artifact format and
notebook projection model. This package assembles the authored document,
runtime configuration, URLs, packaged browser assets, and notebook source
needed by the selected environment.

Live delivery connects the page to an existing Python session or a browser
worker. Static export packages the notebook for WebAssembly execution, stages
the complete site, and preserves the previous destination or a recoverable copy
when replacement fails. A programmatic ASGI application owns its mounted
notebook and Studio services until shutdown.
"""
