# Decision records

Hard-to-reverse choices, one file per decision: `NNNN-short-title.md`.

- Status is one of `proposed`, `accepted`, `superseded by NNNN`.
- Records are never rewritten once accepted. To change a decision, add a new record and
  mark the old one `superseded by NNNN` (that status line is the only edit allowed).
- If a task conflicts with an accepted record, stop and ask before changing anything.

Template:

```markdown
# NNNN: Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
```

| # | Decision | Status |
|---|---|---|
| [0001](0001-license-gpl-3.0-or-later.md) | License: GPL-3.0-or-later | accepted |
| [0002](0002-package-dependency-direction.md) | Package dependency direction and lazy heavy imports | accepted |
| [0003](0003-jsonl-analysis-file-principles.md) | JSONL analysis file principles | accepted |
| [0004](0004-overlay-file-for-user-corrections.md) | User corrections live in a separate overlay file | accepted |
| [0005](0005-per-video-annotations-file.md) | Per-video annotations file for coach events and views | proposed |
| [0006](0006-clip-markers-snap-to-keyframes.md) | Clip export by stream copy, markers snap to keyframes | accepted |
| [0007](0007-ultralytics-as-baseline-detector.md) | Ultralytics YOLO as the baseline detector | accepted |
| [0008](0008-sampled-content-fingerprint.md) | Sampled content fingerprint identifies video files | accepted |
| [0009](0009-frame-index-disk-cache.md) | The frame index is cached on disk | accepted |
