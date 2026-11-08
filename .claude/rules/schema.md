---
paths:
  - "src/openpitch/core/schema/**"
  - "tests/**/test_schema*.py"
  - "docs/design/schema.md"
---

# schema

- Lines are a `type`-discriminated pydantic union (`header`, `calibration`, `frame`; the
  overlay and annotations files have their own record types).
- Files are append-only: header first, then records. Never rewrite earlier lines.
- Bump `schema_version` on breaking changes.
- `pitch_xy` is derived on load and not stored (docs/decisions/0003).
- User corrections go in the overlay file, never the analysis file (docs/decisions/0004).
  Overlay wins on resolve.
- Every record type needs a round-trip test (model -> JSON line -> model).
- Keep docs/design/schema.md in sync until it is replaced by generated docs.
