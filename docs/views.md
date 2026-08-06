---
title: Create and manage views
description: Give several audiences their own pages while reusing one Marimo notebook.
---

# Create and manage views

Create one view for each audience or task that needs a distinct page. Views
reuse the notebook's cells and aliases while owning separate HTML, CSS,
modules, assets, and routes.

## Plan each view around one job

Start with the reader's first question, then choose the notebook results that
answer it.

| View         | Reader job                           | Likely content                                        |
| ------------ | ------------------------------------ | ----------------------------------------------------- |
| `dashboard`  | Explore and adjust the current model | Controls, detailed measures, plots, and tables        |
| `operations` | Find conditions that require action  | Exceptions, thresholds, owners, and next steps        |
| `executive`  | Review the outcome and decision      | Headline measures, material risks, and recommendation |

The [collection research example](examples.md#collection-research-packet) uses
one notebook for corpus discovery, visual study, and packet preparation.

## Add a view

In Studio, open the view menu and choose **New view**. Enter a name such as
`operations` or `executive`.

The equivalent terminal command is:

```console
uvx marimo-studio view add executive analysis.py
```

A view name starts with a lowercase letter and contains lowercase letters,
numbers, or hyphens. The new page starts with every notebook cell in source
order.

List the configured views and current default:

```console
uvx marimo-studio view list analysis.py
```

## Switch between views

Choose a view from the Studio toolbar. Studio keeps the notebook editor and
prepared preview runtimes mounted while the selected page changes.

Link directly to another authored view with a relative URL:

```html
<a href="../executive/">Open the executive brief</a>
```

In the Studio workspace, the link opens the target view while preserving the
current workspace mode. In run mode, the same link opens the target view in
the current browser session.

The configured `default` view opens at `/`. Every named view is also available
at `/<view-name>/`.

## Remove a view

Open the view menu, choose **Remove view**, and confirm the named view. Studio
first saves the active source and prepares a successor view. It retargets the
preview and source stream before deleting the old directory. If the removed
view was the default, Studio makes the first remaining view the new default.

A configured notebook retains at least one view.

## Commit view source

The authored files for `analysis.py` live under:

```text
__marimo__/studio/analysis/<view-name>/
```

Commit this directory with the notebook. If the repository broadly ignores
`__marimo__`, keep the Studio source with targeted rules:

```text
!**/__marimo__/
**/__marimo__/*
!**/__marimo__/studio/
!**/__marimo__/studio/**
```

[Notebook configuration](configuration.md) defines the default view and
runtime. [Design a view](design-views.md) covers projections, styling, assets,
and loading states.
