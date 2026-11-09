# 0010: Derived video files carry their provenance

- Status: proposed
- Date: 2026-11-09

## Context
Coaches work on recodes: 1080p files made by `openpitch recode`, often from a game file
cut out of a longer raw recording by `openpitch clip`. For them the recode is the
original (see design/workflows.md). Their clips and events refer to the recode. Applying
them to the 4K original later (a better export, analysis on the full resolution) needs to
know which file the recode came from and how its timeline and pixels map back.

The mapping itself is simple. `recode` keeps source timestamps and only scales. `clip`
copies packets and shifts timestamps by the pts of its first keyframe. But a coach's
Studio only ever sees the recode, so it cannot write the link into the annotations file
(0005) itself. The link has to travel with the video file, through cloud storage and
across machines.

## Decision
- Every file written by `clip` and `recode` carries its lineage in a container metadata
  tag `org.openpitch.provenance` (an MP4/MOV `mdta` key, written with
  `movflags=use_metadata_tags`; a Matroska tag, which Matroska upper-cases, so readers
  match the key case-insensitively).
- The value is JSON, `{"v": 1, "steps": [...]}`. Steps run from the original footage to
  this file, one per operation, and each new file appends its step to the lineage of its
  source. A step has `op` (`clip` or `recode`), `source` (`content_hash` as in 0008,
  `file_name` as a hint, `width`, `height`, video `time_base`), `pts_offset`,
  `created_at` and `tool`.
- Time maps back per step: `source_pts = seconds / source.time_base + pts_offset`, with
  `seconds` on the made file's timeline. Image coordinates scale to the source size.
  Steps compose, so a recode maps to the raw recording even after the intermediate game
  file is deleted.
- Readers ignore unknown fields, so steps can gain fields (e.g. a crop for twin-mode
  exports) within version 1. A missing, unreadable or newer tag means no lineage, never
  an error.
- When Studio creates an annotations file, it copies the video's lineage into the header
  `derived_from` (0005).

## Consequences
- Files uploaded for coaches can be traced back to the archived originals by fingerprint,
  and clip markers or events can be moved to the 4K file and snapped on its keyframes
  (markers are stored unsnapped, 0005/0006).
- Tools that rewrite metadata (other editors, some uploaders) may drop the tag. The
  lineage is then lost, but the file still works.
- The file name of each source travels with the file. It is only a hint for finding the
  original; identity is the fingerprint.
- Not done yet: reading the lineage to apply annotations to an original. That waits for
  the annotations schema.
