# 0007: Ultralytics YOLO as the baseline detector

- Status: accepted
- Date: 2026-11-08

## Context
Detection and tracking need a starting point. Ultralytics YOLO (+ ByteTrack) is the common
baseline in community football projects and well documented, which suits the
learning goal. Its code and pretrained weights are AGPL-3.0. That is compatible with
GPL-3.0-or-later (0001), but the AGPL terms then apply to a combined work that includes it.
Permissively licensed alternatives exist (RT-DETR, RF-DETR, D-FINE style models), as do
NVIDIA TAO models for Jetson.

## Decision
- Ultralytics is the starting detector and is part of the `gpu` extra.
- It is used only behind core's detector backend abstraction, and it is imported lazily
  (0002). Nothing outside that backend depends on Ultralytics types.
- Weights are downloaded, never committed to the repo.

## Consequences
- The coach build (no `gpu` extra) ships no AGPL code.
- Other detectors can be benchmarked and added later as further backends, on real footage
  (4K Falcon, wide-angle Osmo, 11v11) for small-player recall, identity switches and
  speed. Replacing the default is a new record that supersedes this one.
