# Chart specification

The renderer accepts one UTF-8 JSON object.

## Required fields

```json
{
  "type": "grouped_bar",
  "title": "Throughput at 4K context",
  "categories": ["Prefill", "Decode"],
  "series": [
    {"name": "Engine A", "values": [5749.9, 186.6]},
    {"name": "Engine B", "values": [4737.5, 140.9]}
  ]
}
```

- `type`: `bar`, `grouped_bar`, or `line`.
- `title`: non-empty chart title.
- `categories`: ordered, non-empty string labels.
- `series`: non-empty list of unique names and finite numeric values. Every series must have exactly one value per category.

`bar` accepts exactly one series. `grouped_bar` requires at least two. `line` accepts one or more.
For readable output, one chart accepts at most 24 categories and 6 series; split denser data into multiple charts.

## Optional fields

| Field | Type | Meaning |
| --- | --- | --- |
| `subtitle` | string | Context that materially affects interpretation. |
| `x_label` | string | Horizontal-axis label. |
| `y_label` | string | Vertical-axis label. |
| `unit` | string | Suffix on tick and value labels, such as `%` or `ms`; spacing is handled automatically. |
| `source` | string | User-supplied source note rendered in the footer. |
| `notes` | string | Derivation or caveat rendered in the footer. |
| `show_values` | boolean | Show numeric labels on marks; default `true` for bars and `false` for lines. |
| `y_min` / `y_max` | number | Explicit axis limits. They must contain all values. |
| `allow_truncated_axis` | boolean | Required when a line chart excludes zero from its y-axis. |
| `width` | integer | SVG width from 640 to 2400; default 1200. |
| `height` | integer | SVG height from 400 to 1600; default 750. |
| `colors` | array | One hex color per series, or fewer to cycle. |

## Accuracy rules

- JSON numbers must be finite. `NaN`, `Infinity`, numeric strings, and booleans are rejected.
- The renderer preserves series/category order.
- It does not calculate percentages, averages, rankings, confidence intervals, or missing values.
- If a requested calculation is legitimate, perform it before rendering and describe it in `notes`.
- Mixed units belong in separate charts unless the user explicitly requests and understands a dual-axis chart. Dual axes are intentionally unsupported.

## Local PNG

SVG output uses only Python's standard library. Optional PNG rendering calls a locally installed `rsvg-convert`:

```bash
python3 scripts/render_chart.py spec.json --output chart.svg --png chart.png
```

No network calls or uploads occur.
