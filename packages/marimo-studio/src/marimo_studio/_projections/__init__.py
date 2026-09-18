"""Connect authored page hosts to notebook cells, outputs, and values.

Frontend source requests notebook results through ``<marimo-cell>``,
``<marimo-output>``, and ``mo-value`` hosts. This package resolves each target
to one saved cell or variable, an optional nested value path, and the upstream
cells Marimo must run first. Custom layouts can therefore retain native
notebook computation and output while controlling where each result appears.

Resolution happens before Studio chooses a runtime-specific cell ID. Live
requests are checked against the current notebook and the targets permitted by
the published view. Invalid static declarations produce source diagnostics,
and invalid dynamic requests return bounded browser errors.
"""

STUDIO_RESULT_SELECTOR = (
    ":is(marimo-cell, marimo-output, [mo-value])[data-runtime-cell-id], "
    ":has(> [mo-value][hidden][data-runtime-cell-id]), [data-marimo-lens-inputs], "
    "[data-marimo-lens-target]"
)

# Fallback grouping for authored HTML. Lens retains the exact clicked child as a
# bounded DOM hint while these regions own the outline and selection image.
STUDIO_REGION_SELECTOR = (
    "article, section, header, footer, nav, aside, figure, fieldset, li, tr, "
    "[role=region], [role=group], div:has(> :is(h1, h2, h3, h4, h5, h6))"
)
