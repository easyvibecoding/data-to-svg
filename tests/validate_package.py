#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "data-to-svg"
REQUIRED = [
    ROOT / "LICENSE",
    ROOT / "README.md",
    ROOT / "README.zh-TW.md",
    SKILL / "SKILL.md",
    SKILL / "agents" / "openai.yaml",
    SKILL / "scripts" / "render_chart.py",
    SKILL / "references" / "spec.md",
    SKILL / "examples" / "grouped-bar.json",
    SKILL / "examples" / "heatmap.json",
    SKILL / "examples" / "horizontal-bar.json",
    SKILL / "examples" / "interval.json",
    SKILL / "examples" / "line.json",
    SKILL / "examples" / "line-missing.json",
    SKILL / "examples" / "scatter.json",
    ROOT / "CORPUS_STUDY.md",
]


def main() -> int:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
    if missing:
        print("Missing required files: " + ", ".join(missing), file=sys.stderr)
        return 1

    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    if "TODO" in skill_text or "name: data-to-svg" not in skill_text:
        print("Skill metadata is incomplete", file=sys.stderr)
        return 1
    if "never upload" not in skill_text.lower():
        print("Skill must state its no-upload boundary", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        for example in sorted((SKILL / "examples").glob("*.json")):
            output = Path(tmp) / f"{example.stem}.svg"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL / "scripts" / "render_chart.py"),
                    str(example),
                    "--output",
                    str(output),
                ],
                check=False,
            )
            if result.returncode != 0 or not output.is_file():
                print(f"Example rendering failed: {example.name}", file=sys.stderr)
                return 1
    print("Package validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
