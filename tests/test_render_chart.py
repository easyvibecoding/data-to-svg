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


if __name__ == "__main__":
    unittest.main()
