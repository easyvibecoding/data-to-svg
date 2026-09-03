# Curation corpus shape study

The v1.1 chart expansion was selected from a read-only audit of EasyVibeCoding's published curation corpus on 2026-09-03. The audit inspected `media_manifest` items already marked as charts and classified their numeric transcriptions by shape. It found 637 chart media items across 263 published posts.

The classes overlap: one image can be a time-based percentage matrix, for example. Counts are therefore evidence of recurring shapes, not mutually exclusive totals.

| Observed shape | Posts | Media | Resulting renderer decision |
| --- | ---: | ---: | --- |
| Numeric matrix | 224 | 450 | Add `heatmap`, including explicit `N/A` cells. |
| Percentage values | 140 | 245 | Keep suffix units exact across every chart type. |
| Multi-panel transcription | 108 | 171 | Recommend separate charts when units differ; do not add dual axes. |
| Time axis | 80 | 116 | Let `line` break at a supplied `null` instead of drawing zero. |
| Currency values | 70 | 99 | Add value and axis prefixes such as `$`. |
| Explicit x/y pairs | 27 | 31 | Add `scatter` without inferred trend or Pareto lines. |
| Ranked list | 22 | 25 | Add `horizontal_bar` for long labels and dense rankings. |
| Reported interval | 12 | 12 | Add `interval` for supplied center/low/high values. |

Representative corpus cases included cost-versus-quality model comparisons, ranked provider costs, benchmark matrices, monthly series with an unreported observation, and model accuracy with reported confidence bounds. Qualitative diagrams without explicit coordinates remained out of scope.

This repository contains only aggregate design evidence and neutral example data. The installed skill has no database adapter, network lookup, upload, storage, cache, or publishing path.
