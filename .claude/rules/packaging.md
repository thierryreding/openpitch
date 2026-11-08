---
paths:
  - "pyproject.toml"
  - "uv.lock"
  - ".github/**"
---

# packaging

- Extras: `studio` (PySide6) and `gpu` (torch, torchvision, ultralytics). Base deps stay
  minimal: they are what a coach laptop gets.
- torch/torchvision come from the PyTorch CUDA index on Linux x86_64 and Windows
  (`[tool.uv.sources]`). Other platforms use PyPI.
- License is GPL-3.0-or-later. Check the license of each new dependency (AGPL is fine
  but must stay optional; see docs/decisions/0001).
- CI runs on Windows, macOS and Linux without a GPU. Keep `uv lock --check` passing:
  commit uv.lock with every dependency change.
