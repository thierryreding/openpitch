# 0003: JSONL analysis file principles

- Status: accepted
- Date: 2026-11-08

## Context
core extracts information (detections, tracks, calibration) that Studio loads back for
visualization, possibly on another machine with no GPU. Footage comes from many cameras and
has different resolutions, codecs and frame rates, and the camera may pan and zoom. Twin mode
(two games on two halves of one pitch) needs two analyses of the same video.

## Decision
This record covers the principles only. Field-level details live in the draft schema
(docs/design/schema.md) and may change freely until the pydantic models exist.
- Pydantic models in `openpitch.core` are the source of truth for the schema.
- There is one JSONL file per analyzed *view*: source video + optional crop rectangle +
  pitch model. Twin mode gives two files that reference the same video. The crop is
  virtual: it is recorded in the header, and the footage is never split or re-encoded.
- The first line is a `header`, then records are appended (append-only). Every line has a
  `type` field, which is a discriminated union in pydantic: `header`, `calibration`,
  `frame`.
- The header carries `schema_version`, which is bumped on breaking changes.
- pts (presentation timestamp in stream time_base units) is the source of truth for time.
  The frame index is stored too. Frames are matched to pts with a tolerance, never by
  exact equality.
- Image coordinates are in source-video pixels, never crop-relative.
- Units are metric (pitch coordinates in meters). Yards are a display-only conversion.
- The file is tied to its video by a content hash. Path hints are informational.
- `pitch_xy` is derived data and is not stored. core computes it on load from the
  image-space foot point and the resolved homography. An optional cache can be added
  later if needed.
- Team association is stored per player detection. The header defines the team ids.

## Consequences
- Studio can tail a growing file (live capture later), and jobs can resume from the last
  frame written.
- Re-calibration does not need a new detection run: change the calibration, then
  re-derive the pitch positions.
- Schema round-trip tests must cover every record type once the models exist.
