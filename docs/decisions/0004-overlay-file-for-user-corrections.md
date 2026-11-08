# 0004: User corrections live in a separate overlay file

- Status: accepted
- Date: 2026-11-08

## Context
Machine output gets regenerated: re-extraction with a better model, re-calibration. Manual
corrections made in Studio (team or role fixes, referee marking, manual calibration) must
survive that.

## Decision
- User corrections are never written into the analysis file. They go into a separate
  overlay file next to it, which references the analysis by view id and video hash.
- The overlay uses the same JSONL conventions: a `type`-discriminated union,
  append-only. Draft records: `override` (team/role per track, optionally over a frame
  range, because track ids can switch), `team_seed` (a clicked player used as a team
  prototype), `calibration` with `method: manual`.
- Manual calibration keyframes live in the overlay. The analysis file keeps the auto and
  propagated calibration.
- When core resolves analysis + overlay, the overlay wins.

## Consequences
- Manual calibration can be created before extraction (the pipeline reads it as an anchor)
  or afterwards (only the projection stage is re-run).
- Re-extraction never loses edits. Overrides may need re-mapping if track ids change
  between runs (open).
