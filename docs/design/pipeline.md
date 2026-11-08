# Extraction pipeline

## Stages (proposed)
A staged pipeline, so calibration can be redone cheaply:
1. Detect + track (GPU).
2. Calibrate/propagate homography (mostly CPU). Re-decodes the video and reads the overlay
   anchors.
3. Project to pitch coordinates. `pitch_xy` is derived and not stored
   ([0003](../decisions/0003-jsonl-analysis-file-principles.md)). It is recomputed on load
   from image-space foot points and the resolved homography, using vectorized NumPy:
   seconds for a full match at ~25 detections/frame at 11v11.

Image-space fields are primary. The usual workflow runs the extraction pipeline first,
with manual calibration as the fallback when results are bad. Manual calibration before
any model runs must also be possible.

Candidate pipeline: detection + tracking (YOLO + ByteTrack to start,
[0007](../decisions/0007-ultralytics-as-baseline-detector.md)), field keypoint/line
detection, homography to a pitch model.

## Resolution (proposed)
Analyze at a configurable working resolution, not native. Detector input is far smaller
than 4K/8K, so small or distant players need tiled (sliced) inference or crops, trading
speed for recall. Benchmark on real 4K Falcon and wide-angle footage.

## Views and twin mode
A *view* is a source video + crop rectangle + pitch model (e.g. a half pitch). Analysis
runs per view, so twin mode gives two analysis files referencing the same video. Studio
and a CLI can both define crop rects. Physical split clips can still be produced later via
export, which for a crop means a re-encode.

## Calibration and homography
- Manual calibration is always available as an option (the user clicks known pitch points
  in Studio). Auto-detection is the ideal path, and manual is the fallback when it fails.
  Manual keyframes live in the overlay
  ([0004](../decisions/0004-overlay-file-for-user-corrections.md)).
- Pitch/field model interface (proposed): soccer pitch, American football field with yard
  lines and hash marks, so homography and visualization are sport-agnostic. Metric
  internally. Yards are display-only.
- Static tactical camera (proposed first target): one homography per recording, plus an
  occasional refresh/drift check. Much easier than the auto-tracking camera, and a good
  start for learning.
- Pan/tilt/zoom camera (Falcon, proposed): a camera that rotates and zooms about a roughly
  fixed center relates frames by a homography. Calibrate on keyframes (manual or auto)
  and propagate: H(t -> pitch) = H(t -> keyframe) * H(keyframe -> pitch). Get the
  frame-to-frame H from feature matching or optical flow on the static background, masking
  out detected players. Correct drift by re-anchoring to keyframes and/or field-line
  detection. The user can add manual keyframes where propagation fails. Each frame record
  carries its own homography. Deep point trackers (CoTracker, TAPIR) are a heavier
  alternative to evaluate.
- Lens distortion affects homography. The header `source.lens` records the profile.

## Team assignment
- Stored per player detection (decided).
- Proposed: assign per track (not per frame), using the clicked players as color
  prototypes. Overrides can carry a frame range, since track ids can switch.
- How it is computed (e.g. jersey color clustering) is still open (issue).
