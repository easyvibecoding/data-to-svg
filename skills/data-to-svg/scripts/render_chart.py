#!/usr/bin/env python3
"""Render a validated JSON chart specification as a deterministic local SVG."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


DEFAULT_COLORS = [
    "#0F766E",
    "#C2410C",
    "#1D4ED8",
    "#7C3AED",
    "#A16207",
    "#BE123C",
]
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
CHART_TYPES = {"bar", "grouped_bar", "line"}


class SpecError(ValueError):
    """Raised when a chart specification could misrepresent supplied data."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{field} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise SpecError(f"{field} must be finite")
    return result


def _text(value: Any, field: str, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise SpecError(f"{field} must be a string")
    result = value.strip()
    if required and not result:
        raise SpecError(f"{field} must not be empty")
    return result


def validate_spec(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SpecError("spec must be a JSON object")

    chart_type = _text(raw.get("type"), "type", required=True)
    if chart_type not in CHART_TYPES:
        raise SpecError(f"type must be one of: {', '.join(sorted(CHART_TYPES))}")

    title = _text(raw.get("title"), "title", required=True)
    categories_raw = raw.get("categories")
    if not isinstance(categories_raw, list) or not categories_raw:
        raise SpecError("categories must be a non-empty array")
    if len(categories_raw) > 24:
        raise SpecError("categories supports at most 24 values; split dense data into multiple charts")
    categories = [_text(value, f"categories[{i}]", required=True) for i, value in enumerate(categories_raw)]

    series_raw = raw.get("series")
    if not isinstance(series_raw, list) or not series_raw:
        raise SpecError("series must be a non-empty array")
    if len(series_raw) > 6:
        raise SpecError("series supports at most 6 values; split dense data into multiple charts")

    series: list[dict[str, Any]] = []
    names: set[str] = set()
    for i, item in enumerate(series_raw):
        if not isinstance(item, dict):
            raise SpecError(f"series[{i}] must be an object")
        name = _text(item.get("name"), f"series[{i}].name", required=True)
        if name in names:
            raise SpecError(f"series name must be unique: {name}")
        names.add(name)
        values_raw = item.get("values")
        if not isinstance(values_raw, list) or len(values_raw) != len(categories):
            raise SpecError(f"series[{i}].values must contain exactly {len(categories)} numbers")
        values = [_number(value, f"series[{i}].values[{j}]") for j, value in enumerate(values_raw)]
        series.append({"name": name, "values": values})

    if chart_type == "bar" and len(series) != 1:
        raise SpecError("bar requires exactly one series; use grouped_bar for multiple series")
    if chart_type == "grouped_bar" and len(series) < 2:
        raise SpecError("grouped_bar requires at least two series")

    width = raw.get("width", 1200)
    height = raw.get("height", 750)
    if isinstance(width, bool) or not isinstance(width, int) or not 640 <= width <= 2400:
        raise SpecError("width must be an integer from 640 to 2400")
    if isinstance(height, bool) or not isinstance(height, int) or not 400 <= height <= 1600:
        raise SpecError("height must be an integer from 400 to 1600")

    values = [value for item in series for value in item["values"]]
    explicit_min = raw.get("y_min")
    explicit_max = raw.get("y_max")
    y_min = _number(explicit_min, "y_min") if explicit_min is not None else min(0.0, min(values))
    y_max = _number(explicit_max, "y_max") if explicit_max is not None else max(0.0, max(values))
    if y_min == y_max and explicit_min is None and explicit_max is None:
        y_max = 1.0
    if y_min >= y_max:
        raise SpecError("y_min must be less than y_max")
    if min(values) < y_min or max(values) > y_max:
        raise SpecError("y_min and y_max must contain every plotted value")

    truncated = y_min > 0 or y_max < 0
    allow_truncated = raw.get("allow_truncated_axis", False)
    if not isinstance(allow_truncated, bool):
        raise SpecError("allow_truncated_axis must be a boolean")
    if chart_type in {"bar", "grouped_bar"} and truncated:
        raise SpecError("bar charts must include a zero baseline")
    if chart_type == "line" and truncated and not allow_truncated:
        raise SpecError("a truncated line axis requires allow_truncated_axis: true")

    colors_raw = raw.get("colors", DEFAULT_COLORS)
    if not isinstance(colors_raw, list) or not colors_raw:
        raise SpecError("colors must be a non-empty array")
    colors: list[str] = []
    for i, color in enumerate(colors_raw):
        if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
            raise SpecError(f"colors[{i}] must be a six-digit hex color")
        colors.append(color.upper())

    show_values = raw.get("show_values", chart_type != "line")
    if not isinstance(show_values, bool):
        raise SpecError("show_values must be a boolean")

    return {
        "type": chart_type,
        "title": title,
        "subtitle": _text(raw.get("subtitle"), "subtitle"),
        "categories": categories,
        "series": series,
        "x_label": _text(raw.get("x_label"), "x_label"),
        "y_label": _text(raw.get("y_label"), "y_label"),
        "unit": _text(raw.get("unit"), "unit"),
        "source": _text(raw.get("source"), "source"),
        "notes": _text(raw.get("notes"), "notes"),
        "show_values": show_values,
        "y_min": y_min,
        "y_max": y_max,
        "allow_truncated_axis": allow_truncated,
        "width": width,
        "height": height,
        "colors": colors,
    }


def _nice_step(span: float, target_ticks: int = 5) -> float:
    raw = span / target_ticks
    power = 10 ** math.floor(math.log10(raw))
    fraction = raw / power
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * power


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}".rstrip("0").rstrip(".")
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _with_unit(value: float, unit: str) -> str:
    if not unit:
        return _format_number(value)
    separator = "" if unit.startswith(("%", "‰", "°", "℃")) else "\u00a0"
    return _format_number(value) + separator + unit


def _svg_text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 18,
    anchor: str = "start",
    weight: int = 400,
    fill: str = "#202124",
    rotate: int | None = None,
) -> str:
    transform = f' transform="rotate({rotate} {x:.2f} {y:.2f})"' if rotate is not None else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}"{transform}>{escape(text)}</text>'
    )


def render_svg(spec: dict[str, Any]) -> str:
    width = spec["width"]
    height = spec["height"]
    left, right, top, bottom = 105, 45, 150, 145
    plot_w = width - left - right
    plot_h = height - top - bottom

    data_min = spec["y_min"]
    data_max = spec["y_max"]
    step = _nice_step(data_max - data_min)
    axis_min = math.floor(data_min / step) * step
    axis_max = math.ceil(data_max / step) * step
    if spec["type"] in {"bar", "grouped_bar"}:
        axis_min = min(axis_min, 0.0)
        axis_max = max(axis_max, 0.0)
    if axis_min == axis_max:
        axis_max = axis_min + 1

    def y_pos(value: float) -> float:
        return top + (axis_max - value) / (axis_max - axis_min) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc">',
        "<style>text{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Arial,sans-serif}.axis{stroke:#4B5563;stroke-width:1.5}.grid{stroke:#D1D5DB;stroke-width:1}.mark{shape-rendering:geometricPrecision}</style>",
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        f'<title id="chart-title">{escape(spec["title"])}</title>',
        f'<desc id="chart-desc">{escape(spec["subtitle"] or "Chart generated only from the supplied data.")}</desc>',
        _svg_text(left, 52, spec["title"], size=32, weight=700),
    ]
    if spec["subtitle"]:
        parts.append(_svg_text(left, 84, spec["subtitle"], size=18, fill="#4B5563"))

    legend_x = left
    legend_y = 118
    for i, item in enumerate(spec["series"]):
        color = spec["colors"][i % len(spec["colors"])]
        parts.append(f'<rect x="{legend_x}" y="{legend_y - 14}" width="16" height="16" rx="3" fill="{color}"/>')
        parts.append(_svg_text(legend_x + 24, legend_y, item["name"], size=16))
        legend_x += 38 + max(90, len(item["name"]) * 9)

    tick = axis_min
    tick_guard = 0
    while tick <= axis_max + step / 10 and tick_guard < 20:
        y = y_pos(tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}"/>')
        parts.append(
            _svg_text(
                left - 12,
                y + 6,
                _with_unit(tick, spec["unit"]),
                size=15,
                anchor="end",
                fill="#4B5563",
            )
        )
        tick += step
        tick_guard += 1

    parts.extend(
        [
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}"/>',
            f'<line class="axis" x1="{left}" y1="{top+plot_h}" x2="{width-right}" y2="{top+plot_h}"/>',
        ]
    )

    count = len(spec["categories"])
    slot = plot_w / count
    longest = max(len(label) for label in spec["categories"])
    rotate_labels = longest > 12 or count > 8
    label_y = top + plot_h + 34

    for i, label in enumerate(spec["categories"]):
        x = left + slot * (i + 0.5)
        if rotate_labels:
            parts.append(_svg_text(x + 4, label_y, label, size=15, anchor="end", fill="#374151", rotate=-35))
        else:
            parts.append(_svg_text(x, label_y, label, size=16, anchor="middle", fill="#374151"))

    baseline = y_pos(0.0) if axis_min <= 0 <= axis_max else y_pos(axis_min)
    if spec["type"] in {"bar", "grouped_bar"}:
        series_count = len(spec["series"])
        group_w = slot * 0.72
        gap = min(8.0, group_w * 0.04)
        bar_w = max(3.0, (group_w - gap * (series_count - 1)) / series_count)
        for category_i in range(count):
            group_x = left + slot * category_i + (slot - group_w) / 2
            for series_i, item in enumerate(spec["series"]):
                value = item["values"][category_i]
                value_y = y_pos(value)
                rect_y = min(value_y, baseline)
                rect_h = max(1.0, abs(baseline - value_y))
                x = group_x + series_i * (bar_w + gap)
                color = spec["colors"][series_i % len(spec["colors"])]
                parts.append(
                    f'<rect class="mark" x="{x:.2f}" y="{rect_y:.2f}" width="{bar_w:.2f}" height="{rect_h:.2f}" rx="4" fill="{color}"/>'
                )
                if spec["show_values"]:
                    text_y = rect_y - 8 if value >= 0 else rect_y + rect_h + 20
                    parts.append(
                        _svg_text(
                            x + bar_w / 2,
                            text_y,
                            _with_unit(value, spec["unit"]),
                            size=14,
                            anchor="middle",
                            weight=600,
                            fill=color,
                        )
                    )
    else:
        for series_i, item in enumerate(spec["series"]):
            color = spec["colors"][series_i % len(spec["colors"])]
            points = []
            for category_i, value in enumerate(item["values"]):
                x = left + slot * (category_i + 0.5)
                points.append((x, y_pos(value), value))
            path = " ".join(
                ("M" if i == 0 else "L") + f" {x:.2f} {y:.2f}"
                for i, (x, y, _) in enumerate(points)
            )
            parts.append(
                f'<path class="mark" d="{path}" fill="none" stroke="{color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
            )
            for x, y, value in points:
                parts.append(
                    f'<circle class="mark" cx="{x:.2f}" cy="{y:.2f}" r="6" fill="#FFFFFF" stroke="{color}" stroke-width="4"/>'
                )
                if spec["show_values"]:
                    parts.append(
                        _svg_text(
                            x,
                            y - 12,
                            _with_unit(value, spec["unit"]),
                            size=14,
                            anchor="middle",
                            weight=600,
                            fill=color,
                        )
                    )

    if spec["x_label"]:
        parts.append(
            _svg_text(left + plot_w / 2, height - 55, spec["x_label"], size=17, anchor="middle", weight=600)
        )
    if spec["y_label"]:
        parts.append(
            _svg_text(28, top + plot_h / 2, spec["y_label"], size=17, anchor="middle", weight=600, rotate=-90)
        )

    footer_bits = []
    if spec["source"]:
        footer_bits.append("Source: " + spec["source"])
    if spec["notes"]:
        footer_bits.append("Notes: " + spec["notes"])
    if footer_bits:
        parts.append(_svg_text(left, height - 25, " · ".join(footer_bits), size=13, fill="#6B7280"))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def load_spec(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        raise SpecError(f"input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    return validate_spec(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="UTF-8 JSON chart specification")
    parser.add_argument("--output", "-o", type=Path, required=True, help="output SVG path")
    parser.add_argument("--png", type=Path, help="optional local PNG output path")
    args = parser.parse_args(argv)

    try:
        spec = load_spec(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_svg(spec), encoding="utf-8")
        if args.png:
            converter = shutil.which("rsvg-convert")
            if not converter:
                raise SpecError("--png requires rsvg-convert on PATH")
            args.png.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([converter, str(args.output), "-o", str(args.png)], check=True)
    except (SpecError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
