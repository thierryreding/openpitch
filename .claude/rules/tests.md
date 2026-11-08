---
paths:
  - "tests/**"
---

# tests

- pytest. The default run must pass without a GPU and without the gpu extra.
- Mark GPU tests with `@pytest.mark.gpu` (deselected by default, run with `-m gpu`).
- Use small synthetic videos from `tests/videogen.py` (encoded in-process with PyAV,
  so no ffmpeg binary is needed in CI). Add new structures to `SPECS` in
  `tests/conftest.py`. `numbered` content encodes the frame number (`frame_id`), and
  lossless `patches` content (`COLOR_SPECS`) checks color against `tests/colorref.py`. Tests never touch the real cache: conftest sets
  `OPENPITCH_CACHE_DIR`.
- Never commit real match footage: it shows minors.
- `test_import_boundaries.py` enforces docs/decisions/0002. Fix the import, not the test.
