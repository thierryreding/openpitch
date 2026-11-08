# Workflows (proposed, to confirm)

## 1. Ingest pass (author, first pass over raw footage)
In Studio, mark game ranges in a long raw recording and export one video file per game by
stream copy (keyframe-snapped, [0006](../decisions/0006-clip-markers-snap-to-keyframes.md)).
The game file is the unit everything downstream refers to: its own content hash, a
timeline starting at 0, and smaller to share. The raw recording can be archived. The new
file's annotations header records its provenance (`derived_from`). This is the original
"clip sidecar" idea made concrete: In/Out ranges plus ffmpeg stream-copy export.

## 2. Coach pass (within a game)
Events and notes go in the per-video annotations file
([0005](../decisions/0005-per-video-annotations-file.md)). An event with a time span is a
virtual clip: Studio lists the events, and selecting one jumps to it on the timeline.
Selected events can optionally be exported as files to share with players (e.g. to review
on an iPad), as a stream copy, keyframe-snapped at export time. Point events export with a
configurable pre/post roll.

## Twin mode
One game file, two views. Each view (label, crop rect, sport, pitch model) is defined in
Studio as a `view` record in the annotations file, so it exists before any analysis runs.
The analysis header copies the view. Events carry an optional `view_id`. A physically
cropped video of one half needs a re-encode: it is an on-demand export option, not part of
the ingest pass.

## Live capture (later)
A sideline tap appends an `event` line immediately. Inference runs on a Jetson-class
device and writes append-only JSONL that Studio tails.
