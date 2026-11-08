# OpenPitch: JSONL Schema (draft v0)

Status: DRAFT for review. The principles are accepted in
[0003](../decisions/0003-jsonl-analysis-file-principles.md),
[0004](../decisions/0004-overlay-file-for-user-corrections.md) (overlay) and proposed in
[0005](../decisions/0005-per-video-annotations-file.md) (annotations). Field-level details
below may still change. Eventually these definitions live in pydantic models in
`src/openpitch/core` (the models are the source of truth). Once they exist, this doc is
replaced by docs generated from them.

## Principles
- One JSONL file per analyzed *view* (video + optional crop + pitch model). Twin mode = two files, same video.
- Append-only: first line is the header, then records are appended as analysis progresses. Studio can tail a growing file (live capture later).
- Every line has a `type` field (discriminated union in pydantic): `header`, `calibration`, `frame`.
- pts (presentation timestamp, in stream time_base units) is the source of truth for time. `frame` index is stored too.
- Image coordinates are in source-video pixels (never crop-relative). The crop is only recorded in the header.
- Pitch coordinates are in meters, in a coordinate system defined by the pitch model (origin and axes documented there).
- Frames that were not analyzed (e.g. stride > 1) are simply absent.

## Line type: `header` (first line, exactly one)
| field | notes |
|---|---|
| `schema_version` | integer, bumped on breaking changes |
| `created_at`, `openpitch_version` | provenance |
| `models` | list of `{role, name, version_or_hash}` (detector, tracker, keypoint model, ...) |
| `video` | `{path_hint, content_hash, width, height, fps_nominal, time_base, duration_pts, codec, pix_fmt, color_range, color_space, frame_count}` |
| `source` | `{camera, view_type: tracking\|tactical, camera_motion: static\|ptz, lens: {profile, distortion}}` |
| `view` | `{id, sport: soccer\|american_football, pitch_model: {name, variant}, crop: {x, y, w, h}\|null}` |
| `teams` | list of `{id, label?, color?}` defining the team ids used in detections (typically two per view; goalkeepers/referees may use their own ids or null) |

`path_hint` is informational only; the `content_hash` is how Studio matches analysis to footage on another machine. It is the sampled fingerprint `opfp1:...` (see [0008](../decisions/0008-sampled-content-fingerprint.md)).

## Line type: `calibration` (zero or more, keyframes)
| field | notes |
|---|---|
| `id` | referenced by frames |
| `frame`, `pts` | where it applies |
| `method` | `manual` \| `auto` \| `propagated` |
| `points` | list of `{name?, image: [x, y], pitch: [x, y]}` correspondences (empty if propagated) |
| `homography` | 3x3, row-major, image -> pitch |
| `error` | reprojection error (pitch units) when computed |

## Line type: `frame`
| field | notes |
|---|---|
| `frame`, `pts` | |
| `homography` | optional 3x3 image -> pitch. Present for moving cameras (per frame). Absent for static cameras. |
| `homography_quality` | optional score |
| `calibration_id` | optional; which calibration this frame derives from |
| `detections` | list, see below |

Resolution rule: use the frame's own `homography` if present, otherwise the most recent
`calibration` record at or before the frame.

### Detection
| field | notes |
|---|---|
| `track_id` | integer, stable within a file; null if untracked |
| `cls` | `player` \| `goalkeeper` \| `referee` \| `ball` \| ... (sport-dependent) |
| `conf` | detector confidence |
| `bbox` | `[x1, y1, x2, y2]` source pixels |
| `foot` | optional `[x, y]` image point used for ground position |
| `team` | team id from header `teams` for player detections; null if unassigned/unknown. Stored per detection. |

## Overlay file (user corrections), DECIDED as separate file
Manual corrections made in Studio are NOT written into the analysis file. They go into a separate
overlay file next to it, so the machine output stays untouched and re-extraction does not lose edits.
Draft (not finalized): same JSONL style, header referencing the analysis file (view id, video hash), then
records such as:
- team/role override: `{type:"override", track_id, frames:[start,end]|null, team, cls}` (e.g. mark a track as referee)
- team seed: `{type:"team_seed", frame, track_id, team}` (user clicked a player of a team; used as prototype for assignment)
- manual calibration: `{type:"calibration", ...}` same shape as in the analysis file, with `method: manual` (DECIDED: manual calibration lives in the overlay)
Studio/core resolve analysis + overlay on load (overlay wins). Manual calibration can be created before
extraction (the pipeline reads it as an anchor) or after (auto result was bad, re-run the projection stage).
DECIDED: pitch positions (`pitch_xy`) are NOT stored in the analysis file. They are derived data: core
computes them on load (or per displayed frame) from the image-space foot point and the resolved homography
(overlay manual calibration wins over analysis calibration). Can be added back as an optional cache later if needed.

## Annotations file (per video, human-authored), PROPOSED
Coach annotations (goals, corners, notes) and clips. Tied to a *video*, not to a view or analysis, so it
works on a laptop that has no analysis JSONL at all. Same conventions: JSONL, `type`-discriminated pydantic
union, append-only. Small files that coaches can send around.
| record `type` | fields |
|---|---|
| `header` | `kind: "annotations"`, `schema_version`, `video` (content hash etc.), `derived_from?` (`{content_hash, pts_in, pts_out}` of the raw recording when this video is a game segment exported in the ingest pass) |
| `view` | `id`, `label` (e.g. "Pitch A"), `crop: {x, y, w, h}\|null`, `sport`, `pitch_model`. Defines the views of a game (twin mode = two views). Analysis file headers copy the view they were run on. |
| `event` | `id`, `event_type` (goal, corner, free_kick, foul, kickoff, ... sport vocabulary, free text allowed; plain `clip` for a coach-made clip with no semantic type), `title?`, `view_id?` (which view/twin game it belongs to; a goal on pitch A is not a goal on pitch B), `pts` or `pts_start`/`pts_end`, `team?` (plain label such as home/away, since team ids belong to views), `point?` (image `[x, y]`), `note?`, `tags?`, `clip_id?`, `source: manual\|auto`, `confidence?`, `author`, `created_at` |
| `review` | `event_id`, `verdict: confirm\|reject\|adjust`, adjusted fields, `author` (coach reviewing a machine-detected event) |
| `delete` | `id` (tombstone) |
- Edits and deletes are appended: a later record with the same `id` supersedes the earlier one; `delete` hides it.
- Machine-detected events (future model) are written by the pipeline into the *analysis* file as `event` records with `source: auto`, model id and confidence, because they are reproducible output that may be regenerated. Coaches react through `review` records in the annotations file. Studio merges both. Same principle as the overlay: machine output and human data never share a file.
- Multi-coach: files merge by `id`; `author` says who wrote what.
- Live capture later: a sideline tap appends an `event` line immediately.
- There is no separate `clip` record. A clip is an `event` with `pts_start`/`pts_end`: a virtual clip that is never a separate file unless exported. Studio lists a video's events; selecting one jumps to it on the timeline. Stored pts are exactly what the coach marked; keyframe snapping is applied at export time. Point events (e.g. a goal) can export with a configurable pre/post roll. These are not the ingest-pass game segments (see [workflows.md](workflows.md)).

## Example (abbreviated)
```jsonl
{"type":"header","schema_version":0,"video":{"content_hash":"opfp1:...","width":3840,"height":2160},"source":{"camera":"xbotgo-falcon","view_type":"tracking","camera_motion":"ptz"},"view":{"id":"v1","sport":"soccer","pitch_model":{"name":"soccer-fifa","variant":"full"},"crop":null}}
{"type":"calibration","id":"c1","frame":0,"pts":0,"method":"manual","points":[{"name":"corner_tl","image":[412.0,300.5],"pitch":[0.0,0.0]}],"homography":[1,0,0,0,1,0,0,0,1],"error":0.12}
{"type":"frame","frame":0,"pts":0,"calibration_id":"c1","homography":[1,0,0,0,1,0,0,0,1],"detections":[{"track_id":7,"cls":"player","conf":0.91,"bbox":[100,200,160,330],"team":0}]}
```

## Open points
Tracked as issues (drafts in [docs/issues/](../issues/)): pitch coordinate conventions per
sport, optional pose keypoints, ball handling, how team assignment is computed, and
`.jsonl` vs `.jsonl.zst` compression. Decided: metric internally, yards only for display;
team stored per player detection.
