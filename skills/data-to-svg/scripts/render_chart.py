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


DEFAULT_COLORS = ["#0F766E", "#C2410C", "#1D4ED8", "#7C3AED", "#A16207", "#BE123C"]
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
CATEGORICAL_TYPES = {"bar", "grouped_bar", "horizontal_bar", "line", "heatmap"}
CHART_TYPES = CATEGORICAL_TYPES | {"scatter", "interval"}


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


def _boolean(raw: dict[str, Any], field: str, default: bool) -> bool:
    result = raw.get(field, default)
    if not isinstance(result, bool):
        raise SpecError(f"{field} must be a boolean")
    return result


def _colors(raw: dict[str, Any]) -> list[str]:
    colors_raw = raw.get("colors", DEFAULT_COLORS)
    if not isinstance(colors_raw, list) or not colors_raw:
        raise SpecError("colors must be a non-empty array")
    colors = []
    for i, color in enumerate(colors_raw):
        if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
            raise SpecError(f"colors[{i}] must be a six-digit hex color")
        colors.append(color.upper())
    return colors


def _dimensions(raw: dict[str, Any]) -> tuple[int, int]:
    width = raw.get("width", 1200)
    height = raw.get("height", 750)
    if isinstance(width, bool) or not isinstance(width, int) or not 640 <= width <= 2400:
        raise SpecError("width must be an integer from 640 to 2400")
    if isinstance(height, bool) or not isinstance(height, int) or not 400 <= height <= 1600:
        raise SpecError("height must be an integer from 400 to 1600")
    return width, height


def _bounded_axis(
    values: list[float],
    raw_min: Any,
    raw_max: Any,
    min_field: str,
    max_field: str,
    *,
    include_zero: bool,
    pad: bool = False,
) -> tuple[float, float]:
    explicit_min = _number(raw_min, min_field) if raw_min is not None else None
    explicit_max = _number(raw_max, max_field) if raw_max is not None else None
    data_min, data_max = min(values), max(values)
    padding = (data_max - data_min) * 0.08 if pad and data_min != data_max else 0.0
    if pad and data_min == data_max:
        padding = max(1.0, abs(data_min) * 0.08)
    axis_min = explicit_min if explicit_min is not None else data_min - padding
    axis_max = explicit_max if explicit_max is not None else data_max + padding
    if include_zero:
        if explicit_min is None:
            axis_min = min(0.0, axis_min)
        if explicit_max is None:
            axis_max = max(0.0, axis_max)
    if axis_min == axis_max and explicit_min is None and explicit_max is None:
        axis_min = min(0.0, axis_min) if include_zero else axis_min - 1.0
        axis_max = max(1.0, axis_max) if include_zero else axis_max + 1.0
    if axis_min >= axis_max:
        raise SpecError(f"{min_field} must be less than {max_field}")
    if data_min < axis_min or data_max > axis_max:
        raise SpecError(f"{min_field} and {max_field} must contain every plotted value")
    return axis_min, axis_max


def _validate_series(raw: dict[str, Any], chart_type: str) -> tuple[list[str], list[dict[str, Any]], list[float]]:
    categories_raw = raw.get("categories")
    if not isinstance(categories_raw, list) or not categories_raw:
        raise SpecError("categories must be a non-empty array")
    category_limit = 16 if chart_type == "heatmap" else 24
    if len(categories_raw) > category_limit:
        raise SpecError(f"categories supports at most {category_limit} values for {chart_type}; split dense data into multiple charts")
    categories = [_text(value, f"categories[{i}]", required=True) for i, value in enumerate(categories_raw)]

    series_raw = raw.get("series")
    if not isinstance(series_raw, list) or not series_raw:
        raise SpecError("series must be a non-empty array")
    series_limit = 16 if chart_type == "heatmap" else 6
    if len(series_raw) > series_limit:
        raise SpecError(f"series supports at most {series_limit} values for {chart_type}; split dense data into multiple charts")

    allow_missing = chart_type in {"line", "heatmap"}
    series: list[dict[str, Any]] = []
    numbers: list[float] = []
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
            noun = "numbers or nulls" if allow_missing else "numbers"
            raise SpecError(f"series[{i}].values must contain exactly {len(categories)} {noun}")
        values: list[float | None] = []
        for j, value in enumerate(values_raw):
            if value is None and allow_missing:
                values.append(None)
            else:
                parsed = _number(value, f"series[{i}].values[{j}]")
                values.append(parsed)
                numbers.append(parsed)
        series.append({"name": name, "values": values})
    if not numbers:
        raise SpecError("at least one plotted value must be present")
    if chart_type in {"bar", "horizontal_bar"} and len(series) != 1:
        raise SpecError(f"{chart_type} requires exactly one series; use grouped_bar for multiple series")
    if chart_type == "grouped_bar" and len(series) < 2:
        raise SpecError("grouped_bar requires at least two series")
    return categories, series, numbers


def _validate_scatter(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], tuple[float, float], tuple[float, float]]:
    points_raw = raw.get("points")
    if not isinstance(points_raw, list) or not points_raw:
        raise SpecError("points must be a non-empty array")
    if len(points_raw) > 60:
        raise SpecError("scatter supports at most 60 points; split dense data into multiple charts")
    points: list[dict[str, Any]] = []
    groups: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    for i, item in enumerate(points_raw):
        if not isinstance(item, dict):
            raise SpecError(f"points[{i}] must be an object")
        group = _text(item.get("group"), f"points[{i}].group") or "Data"
        if group not in groups:
            groups.append(group)
        point = {
            "label": _text(item.get("label"), f"points[{i}].label"),
            "group": group,
            "x": _number(item.get("x"), f"points[{i}].x"),
            "y": _number(item.get("y"), f"points[{i}].y"),
        }
        points.append(point)
        xs.append(point["x"])
        ys.append(point["y"])
    if len(groups) > 6:
        raise SpecError("scatter supports at most 6 groups")
    return (
        points,
        groups,
        _bounded_axis(xs, raw.get("x_min"), raw.get("x_max"), "x_min", "x_max", include_zero=False, pad=True),
        _bounded_axis(ys, raw.get("y_min"), raw.get("y_max"), "y_min", "y_max", include_zero=False, pad=True),
    )


def _validate_interval(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[float, float]]:
    points_raw = raw.get("points")
    if not isinstance(points_raw, list) or not points_raw:
        raise SpecError("points must be a non-empty array")
    if len(points_raw) > 24:
        raise SpecError("interval supports at most 24 points; split dense data into multiple charts")
    points: list[dict[str, Any]] = []
    bounds: list[float] = []
    labels: set[str] = set()
    for i, item in enumerate(points_raw):
        if not isinstance(item, dict):
            raise SpecError(f"points[{i}] must be an object")
        label = _text(item.get("label"), f"points[{i}].label", required=True)
        if label in labels:
            raise SpecError(f"interval point label must be unique: {label}")
        labels.add(label)
        value = _number(item.get("value"), f"points[{i}].value")
        low = _number(item.get("low"), f"points[{i}].low")
        high = _number(item.get("high"), f"points[{i}].high")
        if not low <= value <= high:
            raise SpecError(f"points[{i}] must satisfy low <= value <= high")
        points.append({"label": label, "value": value, "low": low, "high": high})
        bounds.extend([low, high])
    return points, _bounded_axis(bounds, raw.get("x_min"), raw.get("x_max"), "x_min", "x_max", include_zero=False, pad=True)


def validate_spec(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SpecError("spec must be a JSON object")
    chart_type = _text(raw.get("type"), "type", required=True)
    if chart_type not in CHART_TYPES:
        raise SpecError(f"type must be one of: {', '.join(sorted(CHART_TYPES))}")
    width, height = _dimensions(raw)
    spec: dict[str, Any] = {
        "type": chart_type,
        "title": _text(raw.get("title"), "title", required=True),
        "subtitle": _text(raw.get("subtitle"), "subtitle"),
        "x_label": _text(raw.get("x_label"), "x_label"),
        "y_label": _text(raw.get("y_label"), "y_label"),
        "unit": _text(raw.get("unit"), "unit"),
        "prefix": _text(raw.get("prefix"), "prefix"),
        "x_unit": _text(raw.get("x_unit"), "x_unit"),
        "x_prefix": _text(raw.get("x_prefix"), "x_prefix"),
        "y_unit": _text(raw.get("y_unit"), "y_unit"),
        "y_prefix": _text(raw.get("y_prefix"), "y_prefix"),
        "source": _text(raw.get("source"), "source"),
        "notes": _text(raw.get("notes"), "notes"),
        "width": width,
        "height": height,
        "colors": _colors(raw),
    }
    if chart_type in CATEGORICAL_TYPES:
        categories, series, values = _validate_series(raw, chart_type)
        spec.update({"categories": categories, "series": series})
        if chart_type == "heatmap":
            value_min, value_max = _bounded_axis(values, raw.get("value_min"), raw.get("value_max"), "value_min", "value_max", include_zero=False)
            spec.update({"value_min": value_min, "value_max": value_max})
        else:
            # Preserve a zero-based default for categorical and line charts.
            # A caller may explicitly truncate a line axis with acknowledgement.
            include_zero = chart_type in {"bar", "grouped_bar", "horizontal_bar", "line"}
            y_min, y_max = _bounded_axis(values, raw.get("y_min"), raw.get("y_max"), "y_min", "y_max", include_zero=include_zero)
            allow_truncated = _boolean(raw, "allow_truncated_axis", False)
            truncated = y_min > 0 or y_max < 0
            if chart_type in {"bar", "grouped_bar", "horizontal_bar"} and truncated:
                raise SpecError("bar charts must include a zero baseline")
            if chart_type == "line" and truncated and not allow_truncated:
                raise SpecError("a truncated line axis requires allow_truncated_axis: true")
            spec.update({"y_min": y_min, "y_max": y_max, "allow_truncated_axis": allow_truncated})
    elif chart_type == "scatter":
        points, groups, x_bounds, y_bounds = _validate_scatter(raw)
        spec.update({"points": points, "groups": groups, "x_min": x_bounds[0], "x_max": x_bounds[1], "y_min": y_bounds[0], "y_max": y_bounds[1]})
    else:
        points, x_bounds = _validate_interval(raw)
        spec.update({"points": points, "x_min": x_bounds[0], "x_max": x_bounds[1]})
    default_values = chart_type in {"bar", "grouped_bar", "horizontal_bar", "interval", "heatmap"}
    spec["show_values"] = _boolean(raw, "show_values", default_values)
    spec["show_labels"] = _boolean(raw, "show_labels", chart_type == "scatter" and len(spec.get("points", [])) <= 20)
    return spec


def _nice_step(span: float, target_ticks: int = 5) -> float:
    raw = span / target_ticks
    power = 10 ** math.floor(math.log10(raw))
    fraction = raw / power
    nice = 1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10
    return nice * power


def _nice_axis(data_min: float, data_max: float, *, include_zero: bool = False) -> tuple[float, float, float]:
    step = _nice_step(data_max - data_min)
    axis_min = math.floor(data_min / step) * step
    axis_max = math.ceil(data_max / step) * step
    if include_zero:
        axis_min, axis_max = min(axis_min, 0.0), max(axis_max, 0.0)
    if axis_min == axis_max:
        axis_max += step
    return axis_min, axis_max, step


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}".rstrip("0").rstrip(".")
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_value(value: float, prefix: str = "", unit: str = "") -> str:
    separator = "" if not unit or unit.startswith(("%", "‰", "°", "℃")) else "\u00a0"
    return prefix + _format_number(value) + (separator + unit if unit else "")


def _svg_text(x: float, y: float, text: str, *, size: int = 18, anchor: str = "start", weight: int = 400, fill: str = "#202124", rotate: int | None = None) -> str:
    transform = f' transform="rotate({rotate} {x:.2f} {y:.2f})"' if rotate is not None else ""
    return f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{fill}"{transform}>{escape(text)}</text>'


def _data_description(spec: dict[str, Any]) -> str:
    intro = spec["subtitle"] or "Chart generated only from the supplied data."
    if spec["type"] in CATEGORICAL_TYPES:
        rows = []
        for item in spec["series"]:
            values = ["missing" if value is None else _format_value(value, spec["prefix"], spec["unit"]) for value in item["values"]]
            rows.append(f'{item["name"]}: ' + ", ".join(f"{category} {value}" for category, value in zip(spec["categories"], values)))
        return intro + " " + " ".join(rows)
    if spec["type"] == "scatter":
        rows = [f'{p["label"] or "point"}: x {_format_value(p["x"], spec["x_prefix"], spec["x_unit"])}, y {_format_value(p["y"], spec["y_prefix"], spec["y_unit"])}' for p in spec["points"]]
        return intro + " " + "; ".join(rows)
    rows = [f'{p["label"]}: {_format_value(p["value"], spec["prefix"], spec["unit"])} [{_format_value(p["low"], spec["prefix"], spec["unit"])}, {_format_value(p["high"], spec["prefix"], spec["unit"])}]' for p in spec["points"]]
    return intro + " " + "; ".join(rows)


def _base_parts(spec: dict[str, Any]) -> list[str]:
    width, height = spec["width"], spec["height"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc">',
        "<style>text{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Arial,sans-serif}.axis{stroke:#4B5563;stroke-width:1.5}.grid{stroke:#D1D5DB;stroke-width:1}.mark{shape-rendering:geometricPrecision}</style>",
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        f'<title id="chart-title">{escape(spec["title"])}</title>',
        f'<desc id="chart-desc">{escape(_data_description(spec))}</desc>',
        _svg_text(105, 52, spec["title"], size=32, weight=700),
    ]
    if spec["subtitle"]:
        parts.append(_svg_text(105, 84, spec["subtitle"], size=18, fill="#4B5563"))
    return parts


def _footer(spec: dict[str, Any]) -> list[str]:
    bits = []
    if spec["source"]:
        bits.append("Source: " + spec["source"])
    if spec["notes"]:
        bits.append("Notes: " + spec["notes"])
    return [_svg_text(105, spec["height"] - 25, " · ".join(bits), size=13, fill="#6B7280")] if bits else []


def _legend(parts: list[str], labels: list[str], colors: list[str]) -> None:
    cursor = 105.0
    for i, label in enumerate(labels):
        color = colors[i % len(colors)]
        parts.append(f'<rect x="{cursor:.2f}" y="104" width="16" height="16" rx="3" fill="{color}"/>')
        parts.append(_svg_text(cursor + 24, 118, label, size=16))
        cursor += 38 + max(90, len(label) * 9)


def _render_vertical(spec: dict[str, Any], parts: list[str]) -> None:
    width, height = spec["width"], spec["height"]
    left, right, top, bottom = 105, 45, 150, 145
    plot_w, plot_h = width - left - right, height - top - bottom
    is_bar = spec["type"] in {"bar", "grouped_bar"}
    axis_min, axis_max, step = _nice_axis(spec["y_min"], spec["y_max"], include_zero=is_bar)

    def y_pos(value: float) -> float:
        return top + (axis_max - value) / (axis_max - axis_min) * plot_h

    _legend(parts, [item["name"] for item in spec["series"]], spec["colors"])
    tick = axis_min
    while tick <= axis_max + step / 10:
        y = y_pos(tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}"/>')
        parts.append(_svg_text(left - 12, y + 6, _format_value(tick, spec["prefix"], spec["unit"]), size=15, anchor="end", fill="#4B5563"))
        tick += step
    parts.extend([f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}"/>', f'<line class="axis" x1="{left}" y1="{top+plot_h}" x2="{width-right}" y2="{top+plot_h}"/>'])
    count = len(spec["categories"])
    slot = plot_w / count
    rotate = max(len(label) for label in spec["categories"]) > 12 or count > 8
    for i, label in enumerate(spec["categories"]):
        x = left + slot * (i + 0.5)
        parts.append(_svg_text(x + (4 if rotate else 0), top + plot_h + 34, label, size=15 if rotate else 16, anchor="end" if rotate else "middle", fill="#374151", rotate=-35 if rotate else None))
    baseline = y_pos(0.0) if axis_min <= 0 <= axis_max else y_pos(axis_min)
    if is_bar:
        series_count = len(spec["series"])
        group_w = slot * 0.72
        gap = min(8.0, group_w * 0.04)
        bar_w = max(3.0, (group_w - gap * (series_count - 1)) / series_count)
        for category_i in range(count):
            group_x = left + slot * category_i + (slot - group_w) / 2
            for series_i, item in enumerate(spec["series"]):
                value = item["values"][category_i]
                assert value is not None
                value_y = y_pos(value)
                rect_y, rect_h = min(value_y, baseline), max(1.0, abs(baseline - value_y))
                x = group_x + series_i * (bar_w + gap)
                color = spec["colors"][series_i % len(spec["colors"])]
                parts.append(f'<rect class="mark" x="{x:.2f}" y="{rect_y:.2f}" width="{bar_w:.2f}" height="{rect_h:.2f}" rx="4" fill="{color}"/>')
                if spec["show_values"]:
                    parts.append(_svg_text(x + bar_w / 2, rect_y - 8 if value >= 0 else rect_y + rect_h + 20, _format_value(value, spec["prefix"], spec["unit"]), size=14, anchor="middle", weight=600, fill=color))
    else:
        for series_i, item in enumerate(spec["series"]):
            color = spec["colors"][series_i % len(spec["colors"])]
            segments: list[list[tuple[float, float, float]]] = []
            segment: list[tuple[float, float, float]] = []
            for category_i, value in enumerate(item["values"]):
                if value is None:
                    if segment:
                        segments.append(segment)
                        segment = []
                else:
                    segment.append((left + slot * (category_i + 0.5), y_pos(value), value))
            if segment:
                segments.append(segment)
            for points in segments:
                if len(points) > 1:
                    path = " ".join(("M" if i == 0 else "L") + f" {x:.2f} {y:.2f}" for i, (x, y, _) in enumerate(points))
                    parts.append(f'<path class="mark" d="{path}" fill="none" stroke="{color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
                for x, y, value in points:
                    parts.append(f'<circle class="mark" cx="{x:.2f}" cy="{y:.2f}" r="6" fill="#FFFFFF" stroke="{color}" stroke-width="4"/>')
                    if spec["show_values"]:
                        parts.append(_svg_text(x, y - 12, _format_value(value, spec["prefix"], spec["unit"]), size=14, anchor="middle", weight=600, fill=color))
    if spec["x_label"]:
        parts.append(_svg_text(left + plot_w / 2, height - 55, spec["x_label"], size=17, anchor="middle", weight=600))
    if spec["y_label"]:
        parts.append(_svg_text(28, top + plot_h / 2, spec["y_label"], size=17, anchor="middle", weight=600, rotate=-90))


def _render_horizontal_bar(spec: dict[str, Any], parts: list[str]) -> None:
    width, height = spec["width"], spec["height"]
    left = min(330, max(170, 80 + max(len(label) for label in spec["categories"]) * 9))
    right, top, bottom = 90, 145, 110
    plot_w, plot_h = width - left - right, height - top - bottom
    axis_min, axis_max, step = _nice_axis(spec["y_min"], spec["y_max"], include_zero=True)
    values = spec["series"][0]["values"]
    color = spec["colors"][0]

    def x_pos(value: float) -> float:
        return left + (value - axis_min) / (axis_max - axis_min) * plot_w

    _legend(parts, [spec["series"][0]["name"]], spec["colors"])
    tick = axis_min
    while tick <= axis_max + step / 10:
        x = x_pos(tick)
        parts.append(f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top+plot_h}"/>')
        parts.append(_svg_text(x, top + plot_h + 29, _format_value(tick, spec["prefix"], spec["unit"]), size=15, anchor="middle", fill="#4B5563"))
        tick += step
    baseline = x_pos(0.0)
    slot, bar_h = plot_h / len(values), max(6.0, plot_h / len(values) * 0.62)
    for i, value in enumerate(values):
        assert value is not None
        y = top + slot * i + (slot - bar_h) / 2
        value_x = x_pos(value)
        rect_x, rect_w = min(baseline, value_x), max(1.0, abs(value_x - baseline))
        parts.append(_svg_text(left - 14, y + bar_h / 2 + 6, spec["categories"][i], size=15, anchor="end", fill="#374151"))
        parts.append(f'<rect class="mark" x="{rect_x:.2f}" y="{y:.2f}" width="{rect_w:.2f}" height="{bar_h:.2f}" rx="4" fill="{color}"/>')
        if spec["show_values"]:
            parts.append(_svg_text(value_x + (9 if value >= 0 else -9), y + bar_h / 2 + 6, _format_value(value, spec["prefix"], spec["unit"]), size=14, anchor="start" if value >= 0 else "end", weight=600, fill=color))
    parts.extend([f'<line class="axis" x1="{left}" y1="{top+plot_h}" x2="{width-right}" y2="{top+plot_h}"/>', f'<line class="axis" x1="{baseline:.2f}" y1="{top}" x2="{baseline:.2f}" y2="{top+plot_h}"/>'])
    if spec["x_label"]:
        parts.append(_svg_text(left + plot_w / 2, height - 52, spec["x_label"], size=17, anchor="middle", weight=600))


def _render_scatter(spec: dict[str, Any], parts: list[str]) -> None:
    width, height = spec["width"], spec["height"]
    left, right, top, bottom = 115, 55, 150, 115
    plot_w, plot_h = width - left - right, height - top - bottom
    x_min, x_max, x_step = _nice_axis(spec["x_min"], spec["x_max"])
    y_min, y_max, y_step = _nice_axis(spec["y_min"], spec["y_max"])

    def x_pos(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def y_pos(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    _legend(parts, spec["groups"], spec["colors"])
    tick = x_min
    while tick <= x_max + x_step / 10:
        x = x_pos(tick)
        parts.append(f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top+plot_h}"/>')
        parts.append(_svg_text(x, top + plot_h + 29, _format_value(tick, spec["x_prefix"], spec["x_unit"]), size=15, anchor="middle", fill="#4B5563"))
        tick += x_step
    tick = y_min
    while tick <= y_max + y_step / 10:
        y = y_pos(tick)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}"/>')
        parts.append(_svg_text(left - 12, y + 6, _format_value(tick, spec["y_prefix"], spec["y_unit"]), size=15, anchor="end", fill="#4B5563"))
        tick += y_step
    parts.extend([f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}"/>', f'<line class="axis" x1="{left}" y1="{top+plot_h}" x2="{width-right}" y2="{top+plot_h}"/>'])
    for point in spec["points"]:
        group_i = spec["groups"].index(point["group"])
        color = spec["colors"][group_i % len(spec["colors"])]
        x, y = x_pos(point["x"]), y_pos(point["y"])
        parts.append(f'<circle class="mark" cx="{x:.2f}" cy="{y:.2f}" r="8" fill="{color}" stroke="#FFFFFF" stroke-width="2"><title>{escape(point["label"] or point["group"])}</title></circle>')
        if spec["show_labels"] and point["label"]:
            parts.append(_svg_text(x + 10, y - 10, point["label"], size=13, weight=600, fill=color))
    if spec["x_label"]:
        parts.append(_svg_text(left + plot_w / 2, height - 50, spec["x_label"], size=17, anchor="middle", weight=600))
    if spec["y_label"]:
        parts.append(_svg_text(28, top + plot_h / 2, spec["y_label"], size=17, anchor="middle", weight=600, rotate=-90))


def _render_interval(spec: dict[str, Any], parts: list[str]) -> None:
    width, height = spec["width"], spec["height"]
    left = min(340, max(190, 90 + max(len(point["label"]) for point in spec["points"]) * 9))
    right, top, bottom = 115, 135, 105
    plot_w, plot_h = width - left - right, height - top - bottom
    x_min, x_max, step = _nice_axis(spec["x_min"], spec["x_max"])

    def x_pos(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    tick = x_min
    while tick <= x_max + step / 10:
        x = x_pos(tick)
        parts.append(f'<line class="grid" x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top+plot_h}"/>')
        parts.append(_svg_text(x, top + plot_h + 29, _format_value(tick, spec["prefix"], spec["unit"]), size=15, anchor="middle", fill="#4B5563"))
        tick += step
    slot, color = plot_h / len(spec["points"]), spec["colors"][0]
    for i, point in enumerate(spec["points"]):
        y = top + slot * (i + 0.5)
        low_x, value_x, high_x = x_pos(point["low"]), x_pos(point["value"]), x_pos(point["high"])
        parts.append(_svg_text(left - 14, y + 6, point["label"], size=15, anchor="end", fill="#374151"))
        parts.append(f'<line class="mark" x1="{low_x:.2f}" y1="{y:.2f}" x2="{high_x:.2f}" y2="{y:.2f}" stroke="{color}" stroke-width="4"/>')
        parts.append(f'<line x1="{low_x:.2f}" y1="{y-8:.2f}" x2="{low_x:.2f}" y2="{y+8:.2f}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<line x1="{high_x:.2f}" y1="{y-8:.2f}" x2="{high_x:.2f}" y2="{y+8:.2f}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<circle class="mark" cx="{value_x:.2f}" cy="{y:.2f}" r="7" fill="{color}" stroke="#FFFFFF" stroke-width="2"/>')
        if spec["show_values"]:
            label = f'{_format_value(point["value"], spec["prefix"], spec["unit"])} [{_format_value(point["low"], spec["prefix"], spec["unit"])}, {_format_value(point["high"], spec["prefix"], spec["unit"])}]'
            parts.append(_svg_text(min(width - right + 8, high_x + 10), y + 6, label, size=13, weight=600, fill=color))
    parts.append(f'<line class="axis" x1="{left}" y1="{top+plot_h}" x2="{width-right}" y2="{top+plot_h}"/>')
    if spec["x_label"]:
        parts.append(_svg_text(left + plot_w / 2, height - 48, spec["x_label"], size=17, anchor="middle", weight=600))


def _mix_color(start: str, end: str, ratio: float) -> str:
    start_rgb = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
    end_rgb = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
    rgb = tuple(round(a + (b - a) * ratio) for a, b in zip(start_rgb, end_rgb))
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


def _render_heatmap(spec: dict[str, Any], parts: list[str]) -> None:
    width, height = spec["width"], spec["height"]
    left = min(300, max(150, 70 + max(len(item["name"]) for item in spec["series"]) * 9))
    right, top, bottom = 150, 145, 145
    plot_w, plot_h = width - left - right, height - top - bottom
    cell_w, cell_h = plot_w / len(spec["categories"]), plot_h / len(spec["series"])
    value_min, value_max, base = spec["value_min"], spec["value_max"], spec["colors"][0]
    for col, label in enumerate(spec["categories"]):
        x = left + cell_w * (col + 0.5)
        rotate = len(label) > 8 or len(spec["categories"]) > 8
        parts.append(_svg_text(x + (4 if rotate else 0), top + plot_h + 30, label, size=14, anchor="end" if rotate else "middle", fill="#374151", rotate=-35 if rotate else None))
    for row, item in enumerate(spec["series"]):
        y = top + cell_h * (row + 0.5)
        parts.append(_svg_text(left - 12, y + 6, item["name"], size=14, anchor="end", fill="#374151"))
        for col, value in enumerate(item["values"]):
            x, y0 = left + cell_w * col, top + cell_h * row
            if value is None:
                fill, label, ratio = "#E5E7EB", "N/A", 0.0
            else:
                ratio = 0.5 if value_max == value_min else (value - value_min) / (value_max - value_min)
                fill = _mix_color("#ECFDF5", base, max(0.0, min(1.0, ratio)))
                label = _format_value(value, spec["prefix"], spec["unit"])
            title = item["name"] + ", " + spec["categories"][col] + ": " + label
            parts.append(f'<rect class="mark" x="{x:.2f}" y="{y0:.2f}" width="{cell_w:.2f}" height="{cell_h:.2f}" fill="{fill}" stroke="#FFFFFF" stroke-width="2"><title>{escape(title)}</title></rect>')
            if spec["show_values"]:
                parts.append(_svg_text(x + cell_w / 2, y0 + cell_h / 2 + 5, label, size=12, anchor="middle", weight=600, fill="#FFFFFF" if value is not None and ratio > 0.55 else "#1F2937"))
    legend_x, legend_y, legend_h = width - 100, top, min(260, plot_h)
    for i in range(40):
        ratio = 1 - i / 39
        parts.append(f'<rect x="{legend_x}" y="{legend_y + legend_h * i / 40:.2f}" width="20" height="{legend_h / 40 + 1:.2f}" fill="{_mix_color("#ECFDF5", base, ratio)}"/>')
    parts.append(_svg_text(legend_x + 30, legend_y + 6, _format_value(value_max, spec["prefix"], spec["unit"]), size=13, fill="#4B5563"))
    parts.append(_svg_text(legend_x + 30, legend_y + legend_h, _format_value(value_min, spec["prefix"], spec["unit"]), size=13, fill="#4B5563"))
    if spec["x_label"]:
        parts.append(_svg_text(left + plot_w / 2, height - 52, spec["x_label"], size=17, anchor="middle", weight=600))
    if spec["y_label"]:
        parts.append(_svg_text(28, top + plot_h / 2, spec["y_label"], size=17, anchor="middle", weight=600, rotate=-90))


def render_svg(spec: dict[str, Any]) -> str:
    parts = _base_parts(spec)
    renderers = {
        "bar": _render_vertical,
        "grouped_bar": _render_vertical,
        "line": _render_vertical,
        "horizontal_bar": _render_horizontal_bar,
        "scatter": _render_scatter,
        "interval": _render_interval,
        "heatmap": _render_heatmap,
    }
    renderers[spec["type"]](spec, parts)
    parts.extend(_footer(spec))
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
