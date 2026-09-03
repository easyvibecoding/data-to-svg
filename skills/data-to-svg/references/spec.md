# Chart specification

The renderer accepts one UTF-8 JSON object. Every chart requires a supported `type` and non-empty `title`.

## Category and matrix charts

`bar`, `grouped_bar`, `horizontal_bar`, `line`, and `heatmap` use ordered categories and series:

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

- `bar` and `horizontal_bar` require exactly one series.
- `grouped_bar` requires at least two series.
- `line` accepts one or more series. A JSON `null` is allowed and creates a visible break; it is never plotted as zero.
- `heatmap` uses series as rows and categories as columns. A JSON `null` is rendered as `N/A`.
- Non-heatmap charts accept at most 24 categories and 6 series. Heatmaps accept up to 16 rows by 16 columns.

## Scatter charts

`scatter` uses exact x/y points. Labels are optional; `group` defaults to `Data`.

```json
{
  "type": "scatter",
  "title": "Task cost versus accuracy",
  "points": [
    {"label": "Model A", "group": "Open", "x": 0.27, "y": 58.5},
    {"label": "Model B", "group": "Hosted", "x": 0.82, "y": 67.4}
  ],
  "x_prefix": "$",
  "y_unit": "%"
}
```

Scatter charts accept at most 60 points and 6 groups. The renderer does not calculate a regression, trend, ranking, correlation, or Pareto frontier.

## Interval charts

`interval` uses supplied center and bound values. Each label must be unique and satisfy `low <= value <= high`.

```json
{
  "type": "interval",
  "title": "Accuracy with reported confidence intervals",
  "points": [
    {"label": "Model A", "value": 57.1, "low": 54.8, "high": 59.4},
    {"label": "Model B", "value": 61.5, "low": 59.1, "high": 63.9}
  ],
  "unit": "%"
}
```

Interval charts accept at most 24 points. Bounds must already exist in the input; the renderer never derives them from an error value, sample size, or distribution.

## Shared optional fields

| Field | Type | Meaning |
| --- | --- | --- |
| `subtitle` | string | Context that materially affects interpretation. |
| `x_label` / `y_label` | string | Axis labels. |
| `unit` | string | Suffix for categorical, heatmap, or interval values, such as `%` or `ms`. |
| `prefix` | string | Prefix for categorical, heatmap, or interval values, such as `$`. |
| `source` | string | User-supplied source note rendered in the footer. |
| `notes` | string | User-requested derivation or caveat rendered in the footer. |
| `show_values` | boolean | Show values on marks. Defaults to true except for line and scatter charts. |
| `show_labels` | boolean | Show scatter point labels. Defaults to true for at most 20 points. |
| `width` | integer | SVG width from 640 to 2400; default 1200. |
| `height` | integer | SVG height from 400 to 1600; default 750. |
| `colors` | array | Six-digit hex colors in series/group order, or fewer to cycle. |

## Axis fields

- Category and line charts accept `y_min` / `y_max`.
- Scatter charts accept `x_min` / `x_max` and `y_min` / `y_max`, plus `x_prefix`, `x_unit`, `y_prefix`, and `y_unit`.
- Interval charts accept `x_min` / `x_max`.
- Heatmaps accept `value_min` / `value_max` for their color range.
- Explicit bounds must contain every plotted value.
- Bar lengths always include zero. Line charts default to a zero-based y-axis; excluding zero requires `allow_truncated_axis: true`.
- Scatter and interval positions default to a padded data range because their marks do not encode magnitude by bar length.

## Accuracy rules

- JSON numbers must be finite. `NaN`, `Infinity`, numeric strings, and booleans are rejected.
- The renderer preserves point, series, category, and group order.
- It does not calculate percentages, averages, rankings, confidence intervals, missing values, or statistical relationships.
- Mixed units belong in separate charts. Dual axes are intentionally unsupported.
- Generated SVG includes a `<title>` and a data-bearing `<desc>` for assistive technology.

## Local PNG

SVG output uses only Python's standard library. Optional PNG rendering calls a locally installed `rsvg-convert`:

```bash
python3 scripts/render_chart.py spec.json --output chart.svg --png chart.png
```

No network calls or uploads occur.
