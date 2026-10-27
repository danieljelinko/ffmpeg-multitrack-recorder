# Notebook cell layout

Applies to every `.ipynb` authored or edited by an agent: reports, drafts, dialogs, nbdev notebooks.

## Headings get their own cell

- Put every heading (`#`, `##`, `###` …) in a markdown cell of its own. The body that follows starts in the
  next cell.
- The title of the notebook is a heading cell too; the byline / recipient / date line goes in the cell after it.
- Why: a heading cell is a stable anchor. Outlines, collapsing, reordering and selective export all work on
  cells, so a heading glued to its body cannot be moved, folded or exported on its own.

## Export is marked per section, on the heading cell

- `<!-- export: <target>[,<target>] -->` as the first line of a heading cell exports that heading and every cell
  under it, down to the next heading of the same or a higher level; subsections inherit it.
- `<!-- export: none -->` on a subheading excludes that subsection (drafts, brainstorming, notes to self).
- The nearest enclosing marker wins; cells under no marker are not exported. Body cells carry no marker.
