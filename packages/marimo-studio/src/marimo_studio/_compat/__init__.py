"""Contain Studio's integration with the pinned Marimo release.

Marimo owns notebook execution, the editor, sessions, controls, virtual files,
and native output rendering. Adapters in this package translate those private
Marimo objects and calls into the records and interfaces used by Studio.

Before Studio starts an adapter, it checks the required Marimo version and the
private APIs that adapter uses. The packaged browser runtime must identify the
same Marimo source release. A Marimo upgrade therefore updates the release
manifest, compatibility checks, browser assets, and affected adapters together.
"""
