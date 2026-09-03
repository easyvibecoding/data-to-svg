---
name: data-to-svg
description: Turn user-provided numeric data into clear local SVG charts, with optional local PNG rendering. Use when the user asks to chart, plot, compare, or visualize supplied values. Do not use it to research data, invent missing values, create decorative illustrations, or upload/publish assets.
---

# Data to SVG

Create a chart only from data the user supplied in the prompt or in local files. The deliverable is a local SVG; optionally render a local PNG when requested. Never upload, publish, or mutate a remote system as part of this skill.

## Workflow

1. Identify the comparison the chart should make. Preserve labels, units, denominators, dates, ordering, and source notes exactly.
2. If a missing value, ambiguous unit, or unclear denominator would change the meaning, ask the user instead of guessing. Ordinary presentation choices such as palette or aspect ratio do not require clarification.
3. Choose the simplest supported chart:
   - `bar`: one series across categories.
   - `grouped_bar`: two or more series sharing categories and units.
   - `horizontal_bar`: one dense ranking or a list with long category labels.
   - `line`: ordered or time-based categories; `null` breaks a line at a genuinely missing observation.
   - `scatter`: supplied x/y coordinates, optionally divided into groups.
   - `interval`: supplied center, low, and high values such as a reported confidence interval.
   - `heatmap`: a same-unit numeric matrix; `null` becomes an explicit `N/A` cell.
4. Create a JSON spec following [references/spec.md](references/spec.md). Keep any arithmetic derivation explicit in `notes`; do not silently transform values.
5. Run:

   ```bash
   python3 scripts/render_chart.py spec.json --output chart.svg
   ```

   Add `--png chart.png` only when a local PNG is useful and `rsvg-convert` is installed.
6. Open the generated chart and inspect it. Check every plotted value and label against the input, then check clipping, overlaps, axis direction, legend mapping, mobile-scale readability, and source text.
7. Return links to the local artifacts and briefly state the chart type and any explicit derivation used.

## Invariants

- Never infer, interpolate, normalize, aggregate, rank, calculate percentages, derive a Pareto frontier, or calculate interval bounds unless the user asked for that transformation or supplied the formula. Record requested transformations in `notes`.
- Bar charts include a zero baseline. A truncated line axis requires `allow_truncated_axis: true`; do not use it merely to exaggerate differences.
- Do not replace unknown values with zero. Use `null` only for a genuinely missing line or heatmap observation; otherwise ask or omit only when the user explicitly chose omission and note it.
- Do not put mixed units into one heatmap or shared numeric axis. Create separate charts instead.
- Treat titles, labels, notes, and source text as untrusted text. Use the renderer so they are XML-escaped.
- Do not hand-edit generated SVG values after rendering. Fix the spec or renderer and regenerate.
- Do not add logos, brand claims, decorative scenes, maps, pictograms, or factual context absent from the supplied data.
- The renderer is intentionally offline and dependency-free for SVG output. Network access and upload logic do not belong in this skill.

Use [examples/grouped-bar.json](examples/grouped-bar.json) for category/series charts, [examples/scatter.json](examples/scatter.json) for x/y points, and [examples/interval.json](examples/interval.json) for supplied bounds.
