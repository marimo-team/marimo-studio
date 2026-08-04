# Create and manage views

One notebook can provide several views. Each view chooses its own notebook
outputs and page structure while sharing the notebook's calculations,
controls, and reactive graph.

## Add a view in Studio

Open the view menu in the Studio toolbar and select **New view**. Enter a name
such as `report` or `operations`.

Studio creates the HTML and CSS, then opens the new source above its live
preview. The notebook remains beside both panes. The starter view places every
notebook cell in source order.

View names start with a lowercase letter and contain lowercase letters,
numbers, or hyphens.

## Add a view from the terminal

The authoring command creates the same starter files:

```console
uvx marimo-studio view add report analysis.py
```

List the notebook's views and current default:

```console
uvx marimo-studio view list analysis.py
```

Keep Marimo running while an agent or another editor changes the new view.
Studio refreshes saved HTML and CSS around the current notebook session.

## Switch views while editing

Choose another name from the view menu. Studio keeps the notebook editor and
prepared preview runtimes mounted while it changes the selected view. Toolbar
selection opens **Side by side**. Links inside a view keep the current mode and
compact pane while restoring the target view's saved split trees.

You can also open a view directly:

```text
/studio/report/
```

The notebook's `default` setting selects the workspace opened from Marimo's
root URL. See [Notebook configuration](reference.md#notebook-configuration) to
change it.

## Design for different audiences

Reuse one notebook source when audiences need different emphasis:

| View        | Typical contents                                  |
| ----------- | ------------------------------------------------- |
| `dashboard` | Controls, current metrics, and operational detail |
| `report`    | Narrative findings, selected charts, and tables   |
| `executive` | Headline measures and decisions                   |

Every view can use the same native cell names and configured aliases. Changes
to notebook code apply to each view that projects the affected cells or
values.

## Remove a view

Open the view menu, select **Remove view**, and confirm the named view. Studio
deletes that view's HTML, CSS, and static files. If you remove the default,
Studio selects the first remaining view as the new default.

A notebook must retain one view. Studio leaves the final view in place.

## Keep views with the notebook

View source for `analysis.py` lives at:

```text
__marimo__/studio/analysis/<view-name>/
```

Commit these directories with the notebook. If the repository ignores
`__marimo__`, keep Studio source with these exceptions:

```text
!**/__marimo__/
**/__marimo__/*
!**/__marimo__/studio/
!**/__marimo__/studio/**
```

Continue with [Design a view](design-views.md) to place notebook cells and
Python values in the page.
