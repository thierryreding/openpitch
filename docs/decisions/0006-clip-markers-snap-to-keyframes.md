# 0006: Clip export by stream copy, markers snap to keyframes

- Status: accepted
- Date: 2026-11-08

## Context
Clips are exported by stream copy (no re-encode) for speed and quality. A stream copy can
only start on a keyframe. On a measured XbotGo Falcon file, keyframes are about 1 s apart
(30 frames at 30 fps), so a naive cut can start up to about 1 s before the In marker.

## Decision
- An In marker snaps to the previous keyframe and an Out marker to the next keyframe, so a
  clip never cuts off anything that was selected.
- Studio shows the snapped positions, so the preview matches the export.
- Keyframe positions are read per file from a keyframe index built by demuxing packets
  (no decoding). They are never assumed. With all-intra or dense-GOP footage, snapping
  does nothing.
- Marker positions are stored as pts on the original timeline. Export always cuts the
  original file, never a proxy.

## Consequences
- Clip editing never needs better than keyframe precision, so keyframe-only scrubbing is
  enough for it.
- Later options, as new records: configurable re-encode for frame-accurate cuts, or smart
  cut (re-encode only the first partial GOP and copy the rest).
