# 0002: Package dependency direction and lazy heavy imports

- Status: accepted
- Date: 2026-11-08

## Context
The package has three parts: `openpitch.core` (all analysis logic and models),
`openpitch.cli` (click command line tools) and `openpitch.studio` (PySide6 UI). Coaches
run Studio on laptops without a capable GPU. Dev workstations and, later, a Jetson run
inference. The same pipeline stages must be usable from both the CLI and Studio.

## Decision
- `core` never imports anything from `cli` or `studio`, not even lazily inside a function.
- `cli` and `studio` depend on `core` only. They never import each other.
- PySide6 is imported only in `studio`.
- Heavy dependencies (torch, ultralytics, onnxruntime, TensorRT, ...) are optional extras
  (`gpu`; Qt is in `studio`). In core they are imported lazily inside functions, so
  `import openpitch.core` works without them.

## Consequences
- core can be installed and tested without Qt or a CUDA stack. The coach build is Studio
  without the `gpu` extra.
- CLI and Studio stay thin frontends over the same core code (a job API, see
  docs/design/architecture.md).
- `tests/test_import_boundaries.py` enforces these rules in CI.
