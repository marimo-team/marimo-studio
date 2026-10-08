# Paper design

A journal preprint set the way LaTeX sets an article: one centered title block
with an abstract, a single justified column, numbered sections, and equations,
theorem environments, and a bibliography in the conventions mathematicians
expect. Live notebook results sit inside the text as if they were typeset
with it.

## Tokens

| Token | Value     | Use                                                 |
| ----- | --------- | --------------------------------------------------- |
| paper | `#fffffc` | Page background                                     |
| ink   | `#1b1b1a` | Text, table rules, and equations                    |
| muted | `#5d5c58` | Subtitle, captions, and the abstract heading        |
| rule  | `#c9c8c2` | The left edge of notebook panels                    |
| link  | `#2a4f7c` | Cross-references, citations, and links              |

## Type

- KaTeX's Computer Modern face for prose, headings, and math, so text and
  equations match. Inline math keeps the text size, and displayed math is set
  10% larger.
- Bold section headings with gray numbers, and an italic subtitle.
- Theorems and propositions set their body in italic, definitions upright,
  and proofs end with a filled square, as amsthm does.

## Layout

- Quarto's article layout with no table of contents and no margin notes.
- Justified prose with hyphenation from 768px wide. Narrower screens use
  ragged-right text and set displayed math at text size.
- Tables follow booktabs: rules above and below the table and under its head,
  tabular figures, and no vertical lines.
- Notebook cells sit behind a thin left rule so readers can tell computed
  output from authored prose.
