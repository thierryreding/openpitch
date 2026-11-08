# Architecture

## Packages
`src/` layout, package `openpitch`:
- `core/`: algorithms and models for analysis (all the logic). Used by both cli and studio.
- `cli/`: CLI applications built with click.
- `studio/`: the PySide6 desktop UI, "Studio".

Dependency direction and lazy heavy imports:
[0002](../decisions/0002-package-dependency-direction.md) (accepted, enforced by
`tests/test_import_boundaries.py`).

Interchange: core writes extracted information to JSONL, and Studio loads it back for
visualization ([0003](../decisions/0003-jsonl-analysis-file-principles.md),
[schema.md](schema.md)).

## Tooling
uv, the hatchling build backend, Python 3.12, ruff (lint + format), pytest. Optional
extras: `studio` (PySide6) and `gpu` (torch, torchvision, ultralytics; CUDA wheels from
the PyTorch index on Linux x86_64 and Windows).

## Running pipeline stages from CLI and Studio
Detect, track and all other pipeline stages are core functionality and can be run from
both the CLI and Studio, so neither the author nor a coach has to switch between them.
This is still subject to a capability check: extraction options appear only when a
capable GPU/backend is present. CPU-only stages (re-calibration, projection) are
available everywhere.

Proposed:
- **Job API** in core: one entry point (run pipeline with a config, a progress callback
  and a cancel token) used by both CLI and Studio, which stay thin frontends.
- Studio runs jobs in a **separate worker process**, not a thread. That isolates CUDA and
  native crashes, avoids the GIL, and keeps the UI responsive. Progress and cancel go
  through the job API. With append-only JSONL, Studio can show partial results while a job
  runs, and jobs can resume from the last frame written.
- **Capability detection** lives in core (is a usable GPU/inference backend present?).
  Studio only queries it, to enable or disable the extraction UI.
- **Inference backend abstraction** (PyTorch / ONNX Runtime / TensorRT), so the same
  pipeline runs on the 4090, the laptop and the Jetson (aarch64). The detector backend
  isolates Ultralytics ([0007](../decisions/0007-ultralytics-as-baseline-detector.md)).
- **Frame-source abstraction** (video file now, live stream later) and incremental,
  append-only JSONL output, so the file-based and live pipelines share code.

## Studio features
- Clip creation: a timeline with multiple In/Out markers and a preview of the footage.
- With a capable GPU, Studio offers to extract information. Otherwise it expects
  extracted info from a separate JSONL file and, if one is present, provides the
  analysis/visualization controls. The goal is that coaches can do analysis on laptops
  without a big GPU.
- Team selection UX: the user clicks a player of each team in a frame to seed team
  assignment, and can manually mark the referee (and fix other roles).
- Manual calibration: the user clicks known pitch points. It is always available.

## Distribution
- Coaches likely use Windows or Mac laptops, so releases must install without a Python
  setup. GitHub Actions builds per platform on Windows/macOS/Linux runners.
- The coach-facing build is Studio without the `gpu` extra (small). GPU variants are for
  the dev workstations and the Jetson, installed from source with uv. No installer.
- Installer tooling and code signing are still open (issue).
