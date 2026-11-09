# 0005: Per-video annotations file for coach events and views

- Status: proposed
- Date: 2026-11-08

## Context
Coaches annotate goals, corners and notes, and make clips, on laptops that may have no
analysis at all. The overlay (0004) is tied to a view and an analysis, so it cannot hold
these.

## Decision (proposed)
- Each video gets a separate annotations file (JSONL, `type`-discriminated, append-only).
  It is tied to the video, not to a view or an analysis.
- Records: `header` (`kind: "annotations"`, video hash, optional `derived_from`: the
  lineage copied from the video's provenance tag, 0010), `view` (label, crop, sport,
  pitch model), `event`, `review`, `delete` (tombstone). A later record with the same
  `id` supersedes the earlier one.
- Views (twin mode) are defined here before any analysis runs. Analysis headers copy the
  view they were run on.
- A clip is an `event` with `pts_start`/`pts_end`. There is no separate clip record. Clips
  stay virtual unless they are exported. Stored pts are exactly what the coach marked, and
  keyframe snapping (0006) is applied at export time.
- Machine-detected events go into the *analysis* file with `source: auto`. Coaches react to
  them with `review` records in the annotations file. Machine output and human data never
  share a file.
- Files from several coaches merge by `id`. `author` records who wrote what.

## Consequences
- Coaches can share small annotation files without the footage or an analysis.
- Still open: the event vocabulary per sport, how video-level events refer to teams, file
  naming and location, and merge conflicts.
