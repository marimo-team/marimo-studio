# Create your first view

Start with a saved [Marimo](https://marimo.io/) notebook, Python 3.11 or newer,
and [uv](https://docs.astral.sh/uv/). The commands below use `analysis.py`.

## Add a dashboard

```console
uvx marimo-studio view add dashboard analysis.py
```

The command adds Studio to the notebook's PEP 723 dependencies and creates:

```text
analysis.py
__marimo__/
  studio/
    analysis/
      dashboard/
        index.html
        app.css
```

The starter page contains every notebook cell in source order, so the first
preview already shows the available outputs.

## Open Studio through Marimo

```console
uv run --with marimo-studio marimo edit analysis.py --sandbox
```

Marimo opens the Studio workspace at its regular server URL. The notebook is
on the left and the live view is on the right. Both use the same edit session.

Open **Pane** in either pane to add the source editor. Place it beside, above,
or below the current pane. Use its **HTML** and **CSS** tabs to edit the view.

## Choose a notebook output

Inspect cells that display a result:

```console
uvx marimo-studio inspect analysis.py --display
```

Use a native Marimo cell name directly. Bind an anonymous cell when the view
needs a stable name:

```console
uvx marimo-studio bind summary analysis.py --cell 3
```

The cell index above is an example. Use the index reported by `inspect`.

## Place the output

Select **HTML** and replace the contents of `#app-shell`:

```html
<main id="app-shell">
  <header>
    <p>Quarterly review</p>
    <h1>Revenue at a glance</h1>
  </header>

  <section aria-labelledby="summary-title">
    <h2 id="summary-title">Summary</h2>
    <marimo-cell name="summary"></marimo-cell>
  </section>
</main>
```

Studio saves the file at
`__marimo__/studio/analysis/dashboard/index.html`. The preview refreshes and
renders the notebook output under **Summary**.

Change a control in the notebook or preview. Marimo sends the value to the
other surface and reruns affected cells. Anywidget model changes follow the
same session path.

You can also edit `index.html` and `app.css` in another editor. Studio follows
changes from disk. If the browser and another editor change the same file,
Studio shows both versions for an explicit choice.

## Check the view

Validate templates, cell names, bindings, and value selectors:

```console
uvx marimo-studio check analysis.py
```

Execute projected cells and resolve projected values before sharing:

```console
uvx marimo-studio check analysis.py --runtime
```

The runtime check can perform the file, network, database, and data access used
by those cells.

Continue with [Create and manage views](views.md) for another audience or
[Design a view](design-views.md) for values, loading space, theming, and HTMX.
