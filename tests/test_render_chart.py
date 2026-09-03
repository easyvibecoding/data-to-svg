import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "data-to-svg" / "scripts" / "render_chart.py"
MODULE_SPEC = importlib.util.spec_from_file_location("render_chart", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
render_chart = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(render_chart)


class RenderChartTests(unittest.TestCase):
    def base_spec(self):
        return {
            "type": "grouped_bar",
            "title": "A & B < comparison",
            "categories": ["One", "Two"],
            "series": [
                {"name": "A", "values": [12, 18]},
                {"name": "B", "values": [10, 20]},
            ],
            "unit": "%",
        }

    def test_grouped_bar_is_valid_accessible_svg(self):
        validated = render_chart.validate_spec(self.base_spec())
        svg = render_chart.render_svg(validated)
        root = ET.fromstring(svg)
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertIn("aria-labelledby", root.attrib)
        self.assertIn("A &amp; B &lt; comparison", svg)
        self.assertEqual(svg.count('class="mark"'), 4)

    def test_line_preserves_series_order_and_escapes_labels(self):
        raw = self.base_spec()
        raw["type"] = "line"
        raw["series"][0]["name"] = "First <series>"
        validated = render_chart.validate_spec(raw)
        svg = render_chart.render_svg(validated)
        self.assertLess(svg.index("First &lt;series&gt;"), svg.index(">B</text>"))
        self.assertEqual(svg.count('<path class="mark"'), 2)
        self.assertEqual(svg.count('<circle class="mark"'), 4)

    def test_rejects_misaligned_values(self):
        raw = self.base_spec()
        raw["series"][0]["values"] = [12]
        with self.assertRaisesRegex(render_chart.SpecError, "exactly 2"):
            render_chart.validate_spec(raw)

    def test_rejects_boolean_as_number(self):
        raw = self.base_spec()
        raw["series"][0]["values"][0] = True
        with self.assertRaisesRegex(render_chart.SpecError, "JSON number"):
            render_chart.validate_spec(raw)

    def test_bar_rejects_truncated_axis(self):
        raw = self.base_spec()
        raw["type"] = "bar"
        raw["series"] = raw["series"][:1]
        raw["y_min"] = 10
        raw["y_max"] = 20
        with self.assertRaisesRegex(render_chart.SpecError, "zero baseline"):
            render_chart.validate_spec(raw)

    def test_line_requires_explicit_truncation_acknowledgement(self):
        raw = self.base_spec()
        raw["type"] = "line"
        raw["y_min"] = 9
        raw["y_max"] = 21
        with self.assertRaisesRegex(render_chart.SpecError, "allow_truncated_axis"):
            render_chart.validate_spec(raw)
        raw["allow_truncated_axis"] = True
        self.assertEqual(render_chart.validate_spec(raw)["y_min"], 9)

    def test_cli_writes_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "spec.json"
            output_path = Path(tmp) / "chart.svg"
            input_path.write_text(json.dumps(self.base_spec()), encoding="utf-8")
            exit_code = render_chart.main([str(input_path), "--output", str(output_path)])
            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.read_text(encoding="utf-8").startswith("<svg"))

    def test_all_zero_values_get_a_visible_default_axis(self):
        raw = self.base_spec()
        for item in raw["series"]:
            item["values"] = [0, 0]
        validated = render_chart.validate_spec(raw)
        self.assertEqual(validated["y_min"], 0)
        self.assertEqual(validated["y_max"], 1)
        self.assertIn('height="1.00"', render_chart.render_svg(validated))

    def test_leading_unit_space_is_preserved(self):
        raw = self.base_spec()
        raw["unit"] = " tok/s"
        svg = render_chart.render_svg(render_chart.validate_spec(raw))
        self.assertIn("20\u00a0tok/s", svg)

    def test_rejects_unreadably_dense_series(self):
        raw = self.base_spec()
        raw["series"] = [{"name": f"S{i}", "values": [i, i + 1]} for i in range(7)]
        with self.assertRaisesRegex(render_chart.SpecError, "at most 6"):
            render_chart.validate_spec(raw)

    def test_horizontal_bar_preserves_rank_order_and_currency_prefix(self):
        raw = {
            "type": "horizontal_bar",
            "title": "Cost ranking",
            "categories": ["First", "Second", "Third"],
            "series": [{"name": "Cost", "values": [2.8, 4.1, 5.6]}],
            "prefix": "$",
        }
        svg = render_chart.render_svg(render_chart.validate_spec(raw))
        self.assertLess(svg.index(">First</text>"), svg.index(">Second</text>"))
        self.assertIn("$5.6", svg)
        self.assertEqual(svg.count('<rect class="mark"'), 3)

    def test_scatter_supports_groups_and_independent_axis_units(self):
        raw = {
            "type": "scatter",
            "title": "Cost versus accuracy",
            "points": [
                {"label": "A", "group": "Open", "x": 0.27, "y": 58.5},
                {"label": "B", "group": "Hosted", "x": 0.82, "y": 67.4},
            ],
            "x_prefix": "$",
            "y_unit": "%",
        }
        validated = render_chart.validate_spec(raw)
        svg = render_chart.render_svg(validated)
        self.assertEqual(validated["groups"], ["Open", "Hosted"])
        self.assertEqual(svg.count('<circle class="mark"'), 2)
        self.assertIn("$0.27", svg)
        self.assertIn("58.5%", svg)

    def test_scatter_rejects_missing_numeric_coordinate(self):
        raw = {"type": "scatter", "title": "Incomplete", "points": [{"label": "A", "x": 1}]}
        with self.assertRaisesRegex(render_chart.SpecError, r"points\[0\]\.y must be a JSON number"):
            render_chart.validate_spec(raw)

    def test_interval_requires_value_inside_supplied_bounds(self):
        raw = {
            "type": "interval",
            "title": "Confidence",
            "points": [{"label": "A", "value": 57.1, "low": 58.0, "high": 59.0}],
        }
        with self.assertRaisesRegex(render_chart.SpecError, "low <= value <= high"):
            render_chart.validate_spec(raw)

    def test_interval_renders_whisker_and_accessible_values(self):
        raw = {
            "type": "interval",
            "title": "Confidence",
            "points": [{"label": "A", "value": 57.1, "low": 54.8, "high": 59.4}],
            "unit": "%",
        }
        svg = render_chart.render_svg(render_chart.validate_spec(raw))
        self.assertEqual(svg.count('class="mark"'), 2)
        self.assertIn("57.1% [54.8%, 59.4%]", svg)

    def test_heatmap_renders_missing_as_na_not_zero(self):
        raw = {
            "type": "heatmap",
            "title": "Matrix",
            "categories": ["Code", "Agent"],
            "series": [
                {"name": "Model A", "values": [72.1, None]},
                {"name": "Model B", "values": [75.8, 81.2]},
            ],
            "unit": "%",
        }
        svg = render_chart.render_svg(render_chart.validate_spec(raw))
        self.assertEqual(svg.count('<rect class="mark"'), 4)
        self.assertIn("Model A, Agent: N/A", svg)
        self.assertIn(">N/A</text>", svg)

    def test_line_null_breaks_path_and_is_not_plotted(self):
        raw = {
            "type": "line",
            "title": "Time series",
            "categories": ["Jan", "Feb", "Mar", "Apr", "May"],
            "series": [
                {"name": "A", "values": [62, 68, None, 76, 81]},
                {"name": "B", "values": [58, 61, 66, 70, 73]},
            ],
            "unit": "%",
        }
        svg = render_chart.render_svg(render_chart.validate_spec(raw))
        self.assertEqual(svg.count('<path class="mark"'), 3)
        self.assertEqual(svg.count('<circle class="mark"'), 9)
        self.assertIn("Mar missing", svg)

    def test_bar_rejects_null_instead_of_treating_it_as_zero(self):
        raw = {
            "type": "bar",
            "title": "Missing",
            "categories": ["A"],
            "series": [{"name": "Value", "values": [None]}],
        }
        with self.assertRaisesRegex(render_chart.SpecError, "JSON number"):
            render_chart.validate_spec(raw)


if __name__ == "__main__":
    unittest.main()
