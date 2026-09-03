# Data to SVG

An open-source Codex skill that turns user-provided numeric data into accurate, local SVG charts.

It is deliberately narrow:

- Data comes from the user's prompt or local files.
- The renderer produces deterministic SVG with no runtime dependencies beyond Python.
- Optional PNG rendering stays local and uses `rsvg-convert` when installed.
- It does not browse for data, invent missing values, upload assets, update databases, or publish content.

## Supported charts

- Single-series bar charts
- Grouped bar charts
- Multi-series line charts

The renderer validates category/value alignment, finite numbers, unique series names, explicit axis bounds, safe XML text, and truthful zero baselines for bars. It intentionally omits dual axes and implicit calculations.

## Install

```bash
git clone https://github.com/easyvibecoding/data-to-svg.git
mkdir -p ~/.codex/skills
cp -R data-to-svg/skills/data-to-svg ~/.codex/skills/
```

Restart Codex so it discovers the skill.

## Use with Codex

```text
Use $data-to-svg to compare these values in a grouped bar chart:
Engine A: prefill 5749.9, decode 186.6
Engine B: prefill 4737.5, decode 140.9
Unit: tokens per second
```

Codex converts the supplied values into the skill's JSON specification, runs the local renderer, inspects the result, and returns the local artifact.

## Use the renderer directly

```bash
python3 skills/data-to-svg/scripts/render_chart.py \
  skills/data-to-svg/examples/grouped-bar.json \
  --output chart.svg
```

Optional local PNG:

```bash
python3 skills/data-to-svg/scripts/render_chart.py \
  skills/data-to-svg/examples/grouped-bar.json \
  --output chart.svg \
  --png chart.png
```

See [the specification](skills/data-to-svg/references/spec.md) for all fields and accuracy rules.

## Validate

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_package.py
```

## Design

The public interface is one small JSON specification and one renderer command. Layout, scaling, escaping, validation, and optional rasterization remain behind that interface. Generated SVGs contain accessible `<title>` and `<desc>` elements and preserve the supplied series/category ordering.

## Origin

This project generalizes a data-figure technique first used in EasyVibeCoding's private editorial workflow. The public renderer and neutral visual system were written for this repository; private branding, database access, storage uploads, cache invalidation, and publication code are not included. No third-party source code is bundled.

## License

[MIT](LICENSE) © 2026 EasyVibeCoding.

Traditional Chinese documentation: [README.zh-TW.md](README.zh-TW.md)
