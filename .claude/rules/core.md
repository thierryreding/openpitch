---
paths:
  - "src/openpitch/core/**"
---

# core

- Never import `openpitch.cli` or `openpitch.studio`, not even inside a function. No Qt.
- Import heavy deps (torch, torchvision, ultralytics, onnxruntime, tensorrt, cv2) lazily
  inside functions. `import openpitch.core` must work with only the base dependencies.
- Ultralytics is used only inside the detector backend. No Ultralytics types leak out.
- Pydantic models are the schema source of truth.
- Units are metric internally (pitch coordinates in meters).
- pts is the time truth. Match frames to pts with a tolerance, never `==`.
- Image coordinates are source-video pixels, never crop-relative.
- Long-running work goes through the job API: progress callback, cancel token,
  append-only output so it can resume.
