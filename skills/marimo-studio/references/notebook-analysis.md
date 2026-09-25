# Notebook analysis

Read when adding or changing notebook computation. Inspect the saved producers
and the relevant live values before editing. Execute changed cells in the live
notebook before checking the view.

For dataset work, keep the notebook markdown-led and reactive. Build named
dataframe results that a Studio view can present or consume.

### Pair one explanation with one analytical cell

Introduce each analytical question with a short markdown cell. Put one focused
Python cell directly after it. The Python cell should derive one well-defined
table, metric, model input, or visualization input from an upstream dataset.

Each fenced block represents one notebook cell:

```python
mo.md("""
## Revenue by segment

Aggregate valid revenue rows so the view can compare segments directly.
""")
```

```python
segment_summary = (
    orders.lazy()
    .filter(pl.col("revenue").is_not_null())
    .group_by("segment")
    .agg(pl.sum("revenue").alias("revenue"))
    .sort("revenue", descending=True)
    .collect()
)
segment_summary
```

The assignment makes `segment_summary` available to downstream cells. The final
expression renders the dataframe as this cell's output. Prefer Polars
expressions for dataframe-native transformations. Use DuckDB when the operation
is clearer as SQL, then materialize a dataframe at the same cell boundary:

```python
segment_summary_sql = duckdb.sql("""
    SELECT segment, SUM(revenue) AS revenue
    FROM orders
    WHERE revenue IS NOT NULL
    GROUP BY segment
    ORDER BY revenue DESC
""").pl()
segment_summary_sql
```

### Keep the reactive dataflow legible

- Load or receive the base dataset once, then derive named results downstream.
- Give each cell one semantic responsibility and one principal result. Separate
  filtering, aggregation, enrichment, modeling, and presentation inputs when
  they answer different questions.
- Prefer expression-based transformations over in-place mutation. Materialize a
  Polars or DuckDB result when the cell establishes a reusable dataframe
  boundary.
- Use domain names such as `filtered_orders`, `segment_summary`, and
  `retention_by_month`. Reserve underscore-prefixed values for cell-local
  helpers.
- Put the dataframe, chart, control, or other intended result in the final
  expression. Keep diagnostic dumps and large unbounded previews out of the
  analytical flow.
- Keep the graph acyclic. Define each shared variable once and let downstream
  cells react to it.

### Parameterize dimensions with Marimo controls

Create a control in one cell, display it as that cell's final expression, and
read its `.value` from downstream transformation cells. Choose the control from
the dimension's datatype and selection semantics:

| Dimension                                 | Marimo control                                     |
| ----------------------------------------- | -------------------------------------------------- |
| One value from a small categorical domain | `mo.ui.dropdown`                                   |
| Several categorical values                | `mo.ui.multiselect`                                |
| Ordered numeric value or interval         | `mo.ui.slider` or `mo.ui.range_slider`             |
| Exact numeric input                       | `mo.ui.number`                                     |
| Date, datetime, or date interval          | `mo.ui.date`, `mo.ui.datetime`, `mo.ui.date_range` |
| Boolean choice                            | `mo.ui.switch` or `mo.ui.checkbox`                 |

Derive options, bounds, and defaults from the dataframe when practical. Keep the
control label tied to the analytical dimension. For example, use one control
cell and one dependent dataframe cell:

```python
segment = mo.ui.dropdown.from_series(orders["segment"], label="Segment")
segment
```

```python
selected_orders = (
    orders
    if segment.value is None
    else orders.filter(pl.col("segment") == segment.value)
)
selected_orders
```
