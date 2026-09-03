# Contributing

Contributions are welcome. Keep the project focused on truthful, offline charts generated from supplied data.

Before opening a pull request:

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_package.py
```

Changes to the chart specification must update its reference documentation and include behavior-level tests. Do not add network access, upload integrations, telemetry, implicit factual enrichment, or silent statistical transformations.
