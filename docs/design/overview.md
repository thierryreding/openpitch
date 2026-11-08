# Overview

## Goals
- Make sideline footage (starting with an XbotGo Falcon camera) easy to use for coaches
  of youth and amateur teams.
- Learn computer vision along the way (an explicit secondary goal).
- Build tools that analyze the footage: player positions, homography to a pitch model, etc.
- Possibly later: live capture from the sideline for near-realtime feedback and half-time
  analysis.

## Scope
- Sports: football (soccer) first, American football second. The design must allow both,
  through a sport-agnostic pitch/field model interface (proposed; see pipeline.md).
- Camera-agnostic: any footage, whatever the camera, resolution, codec or frame rate.
  Planned footage types:
  (a) XbotGo Falcon with auto-tracking, for highlights;
  (b) wide-angle DJI Osmo Action 6 (ordered; reportedly up to 8K) as a tactical recording.
- Twin mode: in youth football, players often split into two teams each and play two
  games in parallel, each on roughly half a pitch. Tactical video is analyzed as two views
  of one video (virtual crop, see [0003](../decisions/0003-jsonl-analysis-file-principles.md)).
- Game formats: small-sided games (e.g. 5v5, 7v7, 9v9) on reduced pitches as well as
  11v11 on a full pitch, with match and half lengths that vary by age group. 11v11
  full-pitch recordings are the hardest case and the benchmark for small-player detection
  and for stage 2 (homography) speed on CPU.

## Users and hardware
- Author: dev laptop with an RTX 3080 Mobile (16 GiB VRAM) and a workstation with an
  RTX 4090, running Arch Linux.
- Coaches: Windows or Mac laptops, possibly without a capable GPU. They must be able to do
  analysis from a JSONL file extracted elsewhere.
- Future: a Jetson Orin NX class device on the sideline for live inference.

## Priorities
- MVP: clips first. Coaches get the most value from clips of the footage that they can
  look at and discuss with players. Overlays and analysis come after: they take longer to
  get done and look good.
- Open source on a public repo (free GitHub CI minutes), GPL-3.0-or-later
  ([0001](../decisions/0001-license-gpl-3.0-or-later.md)). Not intended to be monetized.
- The earlier prototype was only a clipping timeline and is being rewritten from scratch.

## Roadmap (proposed, not yet agreed)
1. Studio clipping MVP: PyAV playback with a pts index, a timeline with multiple In/Out
   markers, clip sidecar, stream-copy export via ffmpeg, a proxy generation CLI, and
   installers for Windows/macOS (CI matrix). Little CV needed.
2. Schema and extraction foundation: pydantic models in core, JSONL read/write, CLI
   detect + track on the static tactical camera (also launchable from Studio via the core
   job API, with progress/cancel), Studio loads JSONL and draws boxes on the video.
3. Pitch model and calibration: manual calibration UI (overlay file), derived pitch
   positions, top-down pitch diagram view.
4. Falcon PTZ homography propagation, team assignment (click-to-seed), twin-mode views,
   auto-calibration.
5. Live capture on Jetson.

CV experiments (detector/tracker comparison, homography) can run alongside phase 1, as
CLI scripts or notebooks for learning.
