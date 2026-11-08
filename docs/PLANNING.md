# OpenPitch: Planning Log

Running record of decisions, so planning can continue in a Claude Code session.
Last updated: 2026-11-08

## Goal
- Make sideline footage (starting with an XbotGo Falcon camera) easy to use for coaches of youth and amateur teams.
- Learn computer vision along the way (explicit secondary goal).
- Build tools that analyze the footage: player positions, homography to a pitch model, etc.
- Possible later: live capture from the sideline for near-realtime feedback and half-time analysis.

## Decisions
- Project name: OpenPitch. Standard Python package, `src/` layout, package dir `src/openpitch`.
- Language: Python.
- Subpackages under `src/openpitch/`:
  - `core/`: algorithms and models for analysis (all the logic). Usable from both cli and studio.
  - `cli/`: set of CLI applications built with click.
  - `studio/`: PySide6 UI, called "studio".
- Interchange format: core extracts information to JSONL; studio loads it back for visualization.
- Sports: football (soccer) is primary. American football is secondary. Design should allow both.
- Hardware: laptop with RTX 3080 Mobile (16 GiB VRAM) and a workstation with an RTX 4090. Coaches' laptops may have no capable GPU.
- Studio features:
  - Clip creation: timeline with multiple In/Out markers, with a preview of the footage.
  - If a capable GPU is available, Studio offers options to extract information.
  - Otherwise Studio expects extracted info from a separate JSONL file; if present, it provides the analysis/visualization controls.
  - Goal: coaches can do analysis on laptops without a big GPU.
- Future idea (vague): live capture setup used from the sideline, inference on something like a Jetson Orin NX, giving coaches near-realtime feedback or data for half-time analysis.
- Video decoding/playback: PyAV (ffmpeg bindings). Chosen because of extensive prior ffmpeg experience and reliability. Concern: performance on coach laptops (see proposals below).
- Clip export: stream copy (keyframe-aligned, no re-encode) for now. CORRECTION after measuring a real Falcon file: keyframes are every ~1 second (every 30 frames at 30 fps), not every couple of frames. With stream copy a clip start therefore snaps to the previous keyframe, up to ~1 s before the In marker. DECIDED handling: clip markers snap to keyframes. An In marker snaps to the previous keyframe, an Out marker snaps to the next keyframe, so a clip never cuts off anything that was selected. Studio shows the snapped positions so the preview matches the export. Keyframe positions are read per file (a keyframe index built by demuxing packets, no decoding), never assumed: other footage may have different spacing, and with all-intra or dense-GOP footage snapping becomes a no-op. Later options: configurable re-encode for frame-accurate cuts, or smart cut (re-encode only the first partial GOP, copy the rest).
- JSONL: one file per video (not split by detections/homography).
- JSONL header carries extra info about the type of footage. Planned footage types: (a) XbotGo Falcon with auto-tracking, for highlights; (b) wide-angle DJI Osmo Action 6 (ordered; reportedly up to 8K) as a tactical recording.
- Software must be camera-agnostic: work with any footage regardless of camera, resolution, codec or frame rate. Falcon has been recording 4K so far and supports several formats/resolutions.
- Twin mode: in youth football, players often split into two teams each and play two games in parallel, each on roughly half a pitch. Tactical video should be analyzable as two separate halves, either via a Studio option or a preprocessing step (mechanism not yet decided, see proposals).
- Twin mode uses a virtual crop, not physically split files. A "view" = source video + crop rectangle + pitch model (e.g. half pitch). Analysis runs per view, so twin mode gives two analysis files (one per half) referencing the same video. Crop rect is stored in the JSONL header; detections stay in source-pixel coordinates. Footage stays untouched, no re-encode. Studio and a CLI can both define crop rects. Physical split clips can still be produced later via clip export if coaches want them.
- Calibration: manual calibration must always be available as an option (user clicks known pitch points in Studio). Auto-detection is the ideal path, manual is the fallback when it fails.
- Schema definitions will be implemented as pydantic models in `openpitch.core` (source of truth). Draft schema discussion lives in `SCHEMA.md`.
- Units: metric internally everywhere (pitch coordinates in meters); convert to yards only for display (American football).
- Team association is stored per player detection (header defines team ids). Computation method (e.g. jersey color clustering) and manual correction in Studio still open.
- User corrections (team, role) live in a separate overlay file, not in the analysis file. Overlay wins when Studio/core resolve the data.
- Studio team selection UX: user clicks a player of each team in a frame to seed team assignment, and can manually mark the referee (and other role fixes).
- Proposed: team assignment operates per track (not per frame) using the clicked players as color prototypes; overrides can carry a frame range since track IDs can switch.
- Manual calibration keyframes live in the overlay file (analysis file keeps auto/propagated calibration). Overlay calibration wins on resolve.
- Workflow: extraction pipeline runs first; manual calibration is the fallback when results are bad. Manual calibration upfront (before models run) must also be possible.
- Proposed: staged pipeline so calibration can be redone cheaply: (1) detect + track on GPU, (2) calibrate/propagate homography (mostly CPU, re-decodes video, reads overlay anchors), (3) project to pitch coordinates. `pitch_xy` is derived data, recomputed by core on load when the overlay changes calibration; image-space fields are primary.
- `pitch_xy` is not stored in the JSONL; it is derived on load from image-space foot points and the resolved homography (cheap: vectorized NumPy, seconds for a full match; ~25 detections/frame at 11v11). Can be added back as an optional cache if really needed.
- Game formats: support small-sided games (e.g. 5v5, 7v7, 9v9) on reduced pitches as well as 11v11 on a full pitch; match and half lengths vary by age group. 11v11 full-pitch recordings are the hardest case: use them to benchmark detection of small players and stage 2 (homography) speed on CPU.
- Tooling: uv, hatchling build backend, Python 3.12, ruff (lint + format), pytest. Optional extras: `studio` (PySide6) and `gpu` (inference stack: torch etc.). Heavy packages are imported lazily so core imports work without them. Dev machine is Arch Linux.
- Distribution: coaches likely use Windows or Mac laptops, so releases must be installable without a Python setup. GitHub Actions can build per-platform on Windows/macOS/Linux runners. Coach-facing build = Studio without the gpu extra (small). GPU variants are for the dev workstations/Jetson and installed from source with uv, no installer needed.
- Open source, public repo (free GitHub CI minutes). Not intended to be monetized.
- MVP priority: clips first. Coaches get the most value from clips of the footage to look at and analyze with players. Overlays/analysis are the author's favorite part but will take longer to get done and look good, so they come after.
- Detect and track (all pipeline stages) are core functionality that must be runnable from both the CLI and Studio, for convenience so the author or a coach does not have to switch between Studio and the command line. Still subject to the capability check (extraction options only shown when a capable GPU/backend is available; CPU-only stages like re-calibration and projection are available everywhere).
- Existing state: research done; prototype is only a clipping timeline and is small enough to regenerate from scratch.

## Proposed, not yet decided
- Core has no dependency on cli or studio (they depend on core only; studio and cli do not import each other). Heavy deps (PySide6, torch, onnxruntime/TensorRT) as optional extras so core/cli install without Qt and Studio installs without a CUDA stack.
- Capability detection lives in core (e.g. is a usable GPU/inference backend present) and Studio only queries it to enable/disable extraction UI.
- Inference backend abstraction in core (PyTorch / ONNX Runtime / TensorRT) so the same pipeline can run on 4090, laptop, and Jetson (aarch64).
- Frame-source abstraction (video file now, live stream later) and incremental, append-only JSONL output, so the file-based pipeline and a live pipeline share code and Studio can tail a growing file.
- JSONL tied to its video via video identifier (e.g. content hash) plus frame index and timestamp, so Studio can match analysis to footage on a different machine.
- Frame-accurate seeking is needed for clipping and for overlay lookup in Studio, but not for extraction, which decodes sequentially. Use pts (not frame count) as the source of truth, since footage may be variable frame rate; JSONL records store both frame index and pts.
- Clips stored as a small sidecar (JSON) of In/Out ranges; actual export via ffmpeg.
- Sport abstraction: a pitch/field model interface (soccer pitch, American football field with yard lines and hash marks) so homography and visualization are sport-agnostic.
- Camera pans/zooms (auto-tracking), so a single static homography will not work. Estimate homography per frame or per keyframe from visible field lines, with temporal smoothing. Each frame record carries its own homography matrix next to detections. Include a schema version field.
- JSONL header `source` block: camera model, view type (tracking vs tactical), camera motion (moving vs static), lens info (wide-angle distortion/lens profile, since distortion affects homography), resolution, fps.
- Static tactical camera is much easier than the auto-tracking one: one homography per recording plus occasional refresh/drift check. Good first target for learning and for the homography code; Falcon tracking footage comes after.
- Homography over a pan/tilt/zoom video (Falcon): a camera that rotates/zooms about a roughly fixed center relates frames by a homography, so calibrate on keyframes (manual or auto) and propagate: H(t -> pitch) = H(t -> keyframe) * H(keyframe -> pitch). Frame-to-frame H from feature matching or optical flow on static background, masking out detected players. Drift is corrected by re-anchoring to keyframes and/or field-line detection; user can add more manual keyframes where propagation fails. Deep point trackers (e.g. CoTracker/TAPIR) are an alternative to evaluate, heavier.
- Resolution-agnostic pipeline: analyze at a configurable working resolution rather than native; detector input is far smaller than 4K/8K, so small/far players need tiled (sliced) inference or crops, trading speed for recall. Benchmark on real 4K Falcon and wide-angle footage.
- 8K and high-bitrate HEVC will not decode in real time on weak coach laptops: low-res proxy files for Studio preview/scrubbing (generated by a CLI), hardware decode where available.
- Multi-segment recordings: header `video` may need a list of segments (files with hash, offset) forming one virtual timeline, if cameras split long recordings. Handle pixel formats beyond 8-bit 4:2:0 (10-bit) in the decode layer.
- Job API in core: a single entry point (e.g. run pipeline with config, progress callback, cancel token) used by both CLI and Studio, so they are thin frontends over the same code. Studio runs jobs in a separate worker process (not a thread): isolates CUDA/native crashes and the GIL, and the UI stays responsive. Progress and cancel via the job API; append-only JSONL lets Studio show partial results while running and lets jobs resume from the last written frame.
- Scrubbing: fast mode shows keyframes only (seek to a keyframe, decode just that frame; PyAV can also skip non-key frames in the codec context). Since markers snap to keyframes, clip editing never needs more precision than that. Precise (frame-by-frame) stepping decodes forward from the previous keyframe, at most one GOP, with a small frame cache; needed mainly for viewing analysis overlays. Fast mode vs precise mode is chosen by the Studio use case, not by the file.
- Proxy for playback: optional low-res (e.g. 720p) copy for smooth playback of 4K/8K on weak laptops (and a dense-GOP/all-intra variant if precise stepping on slow machines matters). With keyframe-only scrubbing the proxy is no longer needed for clip editing. Marker positions are stored as pts on the original timeline; export always cuts the original file.
- Coach annotations (goals, corners, notes) as JSONL, PROPOSED as a separate per-video annotations file rather than part of the overlay: the overlay is tied to a view/analysis, but coaches must be able to annotate on laptops with no analysis at all. Same principles as the overlay (human data separate from machine output, append-only). Coach clips are just events with a time span (no separate clip record): Studio lists the events, selecting one jumps to it on the timeline, and a clip stays virtual, never a separate file, unless exported. Optional export (e.g. to review with the team on an iPad) is a stream copy, keyframe-snapped at export time. Game segments are different, see "Two workflows". Machine-detected events later go into the analysis file with source auto; coaches confirm/reject/adjust via review records. Details in SCHEMA.md.
- Two workflows (PROPOSED, to confirm):
  1. Ingest pass (author, first pass over raw footage): in Studio, mark game ranges in a long raw recording and export one video file per game by stream copy (keyframe-snapped). The game file is the unit everything downstream refers to (content hash, timeline starting at 0, smaller to share), and the raw recording can be archived. Provenance is recorded in the new file's annotations header (`derived_from`). This is the original "clip sidecar" idea made concrete: In/Out ranges plus ffmpeg stream-copy export.
  2. Coach pass (within a game): events and notes in the annotations file; an event with a time span is a virtual clip. Optional export of selected events as files to share with players.
- Twin mode: one game file, two views. Each view (label, crop rect, sport, pitch model) is defined in Studio as a `view` record in the annotations file, so it exists before any analysis runs; the analysis header copies the view (crop embedded there, as decided). No physical split. Events carry an optional `view_id`. A physically cropped video for sharing one half is possible but needs a re-encode: an on-demand export option, not part of the ingest pass.
- Candidate pipeline: detection + tracking (e.g. YOLO + ByteTrack), field keypoint/line detection, homography to a pitch model.

## Open questions
- Falcon footage, observed on a real recording: single MP4, HEVC Main 8-bit, yuv420p full range (pc), bt709, 3840x2160, 30 fps (avg and real frame rate agree, likely constant), ~38.7 Mb/s (~290 MB/min, so ~5.4 GB for this 18:31 file and ~8.7 GB for a 30 minute half), AAC stereo audio, muxed by libavformat 61.7 (file was remuxed/processed by an FFmpeg-based tool). Keyframes measured every ~1.0 s (30 frames); packet pts are in microsecond time base with small jitter (e.g. 5.000022), so match frames to pts with a tolerance, never by exact equality. Still unknown: whether long recordings get split into several files, how footage is retrieved from the camera, and whether pts are truly constant-rate.
- Decode layer must handle full-range (pc) YUV correctly when converting to RGB for display and analysis. Store pix_fmt, color_range, color_space in the JSONL header `video` block.
- What does the existing prototype contain, and where does it live?
- What do the coaches need to see first (clips only, or overlays/stats)?
- How will footage be shared with coaches (export, hosting, privacy of minors in video)?
- JSONL schema details (per-frame vs per-track records, units, coordinate frames)?
- Dependency/tooling choices: build backend, env manager (uv?), lint/test setup, Python version?
- DJI Osmo Action 6: lens/field of view, how to get a lens distortion profile (known profile vs own checkerboard calibration with OpenCV), codec/bit depth (10-bit HEVC? D-Log/HLG?), and recording limits (long recordings may be split into multiple files).
- Time sync between Falcon and wide-angle recordings of the same match (needed if views are ever combined).
- Pitch model for twin mode: half-pitch landmarks differ (cones/boundaries instead of full lines); how is homography defined there?
- License: DECIDED GPL-3.0-or-later. Motivation: amateur clubs should not have to pay exorbitant amounts for analysis; commercial use is acceptable but anyone who changes and distributes it must contribute back (no proprietary forks). Author is a Linux kernel developer and likes copyleft. (Remaining detail below is background on dependency compatibility.) Note GPL-2.0-only is NOT compatible with AGPL-3.0 dependencies; GPL-3.0 is (explicit AGPLv3 section 13 / GPLv3 section 13 combination clause), with AGPL terms applying to the combined work. Keep Ultralytics isolated behind the detector backend abstraction as an optional extra so it stays replaceable. GPL does not prevent selling copies or hosting; it only prevents proprietary closed forks (AGPL also covers hosted services). Constrained by dependencies: Ultralytics YOLO code and its pretrained weights are AGPL-3.0 (using it pulls the project toward AGPL, alternatives exist: other detectors under permissive licenses, e.g. RT-DETR/RF-DETR/D-FINE-style models, check each); PySide6 is LGPL (fine for any license, keep dynamic linking in mind for installers); check the license of the ffmpeg build bundled in PyAV wheels; check licenses of model weights and training datasets.
- Annotations: event vocabulary per sport (soccer vs American football), how team is referenced for video-level events, file naming/location next to the video, and merging annotation files from several coaches.
- Event export for review on iPads: one file per event vs one concatenated reel of selected events; the Falcon file uses the hvc1 HEVC tag, which Apple devices play, but 4K at ~38 Mb/s may be heavy, so a re-encoded 1080p export option may be wanted later; default pre/post roll for point events.
- Installer tooling for coach releases (PyInstaller vs pyside6-deploy/Nuitka vs Briefcase), code signing (macOS notarization needs a paid Apple developer account; unsigned Windows installers trigger SmartScreen warnings), and whether the repo is public (free CI minutes) or private.
- Apple Silicon/macOS acceleration (MPS/CoreML) vs CUDA-only for the gpu extra: out of scope for now?
- PyAV playback performance on weak laptops: footage resolution/codec decides this. Mitigations to evaluate: pts index of the file, decoded-frame cache, low-res proxy for scrubbing, hardware decode.

## Repo scaffolding: agent rules files
DECIDED: scaffolding sets up the standard agent instruction files, plus per-directory rules in `.claude/rules/`.
- `AGENTS.md` at repo root: canonical, vendor-neutral instructions (project overview and mission, layout, commands such as uv sync / ruff / pytest, conventions, license, pointers to docs).
- `CLAUDE.md` at repo root: starts with the one-line import `@AGENTS.md`, then only Claude Code specific notes. Reason: Claude Code reads AGENTS.md on its own only when no CLAUDE.md exists, so CLAUDE.md must import it.
- `.claude/rules/*.md`: scoped rules with `paths:` globs in YAML frontmatter, loaded when Claude reads or edits matching files. A rules file without `paths` loads at launch like CLAUDE.md, so always scope them.
- Keep root files short (they cost context every session, and long files hide contradictions). These files are context, not enforcement: enforce with ruff, pytest, CI and hooks. Run `/doctor prompt-audit` now and then to catch stale or conflicting instructions.
- Move PLANNING.md and SCHEMA.md into `docs/` once the repo exists; link them from AGENTS.md rather than importing them (imports load into context every session).

Proposed rule files (content to draft during scaffolding):
- `core.md` (`src/openpitch/core/**`): never import cli or studio; no Qt; heavy deps (torch, ultralytics, onnxruntime) imported lazily inside functions; pydantic models are the schema source of truth; metric units internally; pts is the time truth, match frames with tolerance; image coordinates are source pixels.
- `studio.md` (`src/openpitch/studio/**`): PySide6 lives only here; no analysis logic (call the core job API); long jobs run in a worker process; the UI thread never decodes video; imports core only.
- `cli.md` (`src/openpitch/cli/**`): click; thin wrappers over core, no business logic; progress and cancel via the core job API.
- `schema.md` (schema modules and their tests): `type`-discriminated union (header, calibration, frame), append-only JSONL, bump `schema_version` on breaking changes, `pitch_xy` is derived and not stored, overlay file holds user corrections.
- `tests.md` (`tests/**`): pytest; tests must pass without a GPU; mark GPU tests; use small synthetic fixture videos generated with ffmpeg; never commit real match footage (it shows minors).
- `packaging.md` (`pyproject.toml`, `.github/**`): extras `studio` and `gpu`; CI matrix for Windows/macOS/Linux; GPL-3.0-or-later license; keep dependencies minimal.

## Models and references to evaluate (nothing decided)
- Ultralytics YOLO (+ ByteTrack, supervision): the common baseline in community football projects (detect/track players, referees, ball; KMeans shirt colors for teams; optical flow for camera motion; perspective transform). AGPL-3.0 code and weights: compatible with GPL-3.0-or-later, keep isolated behind the detector backend as an optional extra.
- Permissively licensed detectors (RT-DETR family etc.): alternatives if the AGPL dependency becomes a problem. Check each license.
- SoccerNet (soccer-net.org, github.com/SoccerNet): dataset/benchmark platform for broadcast soccer video: action spotting, ball action spotting, tracking (with jersey numbers and teams), camera calibration, re-identification. Interesting for: released calibration network (distilled from a commercial tool, trained on 500 broadcast games) as an auto-calibration candidate; action spotting to auto-suggest clips (long term). Caveat: broadcast footage looks very different from sideline/fixed cameras, so transfer must be tested. Check dataset and model licenses.
- NVIDIA TAO models on NGC (PeopleNet, PeopleNet-Transformer, pose, action recognition, re-identification): optimized for TensorRT/DeepStream and Jetson (Orin NX supported), so a candidate backend for the Jetson live phase. Caveats: model cards say usable only with TAO/DeepStream/TensorRT; PeopleNet-Transformer not trained on fish-eye or moving cameras; people-only classes (no ball, no team/referee); fine-tuning would need labeled football data; NVIDIA Open Model License has an acceptable-use addendum and may be updated, GPL compatibility unclear. Do not bundle weights in the repo; download separately.
- Benchmark all candidates on real footage (4K Falcon, wide-angle Osmo, small-sided and 11v11 games) for small-player recall, tracking identity switches and speed.

## Proposed roadmap (not yet agreed)
1. Studio clipping MVP: PyAV playback with pts index, timeline with multiple In/Out markers, clip sidecar (JSON), stream-copy export via ffmpeg, proxy generation CLI, installers for Windows/macOS (CI matrix). Little CV needed.
2. Schema and extraction foundation: pydantic models in core, JSONL read/write, CLI detect + track on the static tactical camera (also launchable from Studio via the core job API, with progress/cancel), Studio loads JSONL and draws boxes on the video.
3. Pitch model and calibration: manual calibration UI (overlay file), derived pitch positions, top-down pitch diagram view.
4. Falcon PTZ homography propagation, team assignment (click-to-seed), twin-mode views, auto-calibration.
5. Live capture on Jetson.
CV experiments (detector/tracker comparison, homography) can run in parallel to phase 1 as CLI scripts or notebooks for learning.

## Next steps
- Agree on roadmap, then scaffold the repo (pyproject with extras, src/openpitch/{core,cli,studio}, GPL-3.0 license, ruff/pytest, CI skeleton, AGENTS.md + CLAUDE.md + .claude/rules/ as described above) in Claude Code.
- First scaffolding task: split this planning doc into the repo's documentation structure. Decision records (ADR style, `docs/decisions/NNNN-title.md`, status proposed/accepted/superseded, never rewritten, superseded by a new record) for hard-to-reverse choices: license, dependency direction (core never imports cli/studio), schema shape, overlay vs annotations split, keyframe-snapping rule. Living design docs in `docs/design/` (architecture, pipeline stages) edited in place. Open questions and tasks become GitHub issues (labels such as `question`, `decision-needed`). Once the pydantic models exist, generate schema docs from them and retire SCHEMA.md.
- Keep docs and code in sync: change the doc in the same commit/PR as the code that contradicts it. AGENTS.md gets a rule: if a task conflicts with a decision record, stop and ask, then update the record. Enforce critical boundaries in tests/CI (import-boundary check, schema round-trip tests, no-GPU test run), since docs and rules files are context, not enforcement. At the end of a Claude Code session, ask whether any decision changed and update the records.
- Open items that block nothing in phase 1: detector/tracker choice, pitch conventions, lens calibration.
- ffprobe a real Falcon file to confirm keyframe spacing, codec and VFR.
