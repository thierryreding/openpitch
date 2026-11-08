---
paths:
  - "tests/**"
---

# tests

- pytest. The default run must pass without a GPU and without the gpu extra.
- Mark GPU tests with `@pytest.mark.gpu` (deselected by default, run with `-m gpu`).
- Use small synthetic fixture videos generated with ffmpeg (e.g. testsrc, with a short
  GOP), created in a fixture or kept tiny in `tests/fixtures/`.
- Never commit real match footage: it shows minors.
- `test_import_boundaries.py` enforces docs/decisions/0002. Fix the import, not the test.
