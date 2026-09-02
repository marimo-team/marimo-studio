"""Describe saved notebook structure and selected runtime results.

Static inspection turns notebook source into source-derived cell identities,
names, locations, definitions, references, and dependency relationships
without running cell bodies. Views, projections, validation, and agents use
that model before mapping a saved cell to its current Marimo runtime ID.

Explicit runtime inspection runs the saved notebook through Marimo and reports
status, MIME output, and JSON-compatible values for the selected cells. It
compares the saved source before and after execution so the returned result
belongs to one notebook revision.
"""
