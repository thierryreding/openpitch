---
paths:
  - "src/openpitch/studio/**"
---

# studio

- PySide6 is imported only in this package.
- Studio imports `openpitch.core` only, never `openpitch.cli`.
- No analysis logic here: call the core job API.
- Long jobs run in a separate worker process, not a thread.
- The UI thread never decodes video.
- Enable extraction UI only when core's capability check says a backend is available.
  CPU-only stages (re-calibration, projection) are always available.
- Show keyframe-snapped clip positions, so the preview matches the export
  (docs/decisions/0006).
- Yards are a display conversion only. Data stays metric.
