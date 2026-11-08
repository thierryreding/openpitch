---
paths:
  - "src/openpitch/cli/**"
---

# cli

- click commands are thin wrappers over core. No business logic here.
- Import `openpitch.core` only, never `openpitch.studio` or PySide6.
- Progress and cancel (Ctrl+C) go through the core job API.
- Keep module-level imports light: `openpitch --help` must not load torch.
