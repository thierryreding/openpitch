# OpenPitch

Football video tools for amateur coaches: clips from sideline footage first, then player
detection, tracking and pitch analysis. Soccer first, American football second. Also a
computer vision learning project. Coaches run Studio on Windows/Mac laptops that may have
no capable GPU, so analysis must work from JSONL extracted elsewhere.

## Layout
- `src/openpitch/core/`: all analysis logic and models (pydantic schema = source of truth).
- `src/openpitch/cli/`: click commands, thin wrappers over core.
- `src/openpitch/studio/`: PySide6 desktop UI ("Studio").
- `tests/`: pytest, must pass without a GPU.
- `docs/decisions/`: decision records (ADRs). `docs/design/`: living design docs.
- `tools/benchmarks/`: raw measurement scripts. `openpitch bench-decode` compares decoders.

core never imports cli or studio, and cli and studio never import each other
(docs/decisions/0002). Heavy deps (torch, ultralytics, PySide6) are optional extras and
imported lazily.

## Commands
```sh
uv sync                    # add --extra studio and/or --extra gpu as needed
uv run pytest              # gpu tests are deselected; run them with -m gpu
uv run ruff check --fix
uv run ruff format
```

## Conventions
- Python 3.12, ruff for lint and format (line length 100).
- Every source file starts with `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Time is pts, never frame counts. Image coordinates are source pixels. Pitch units are
  meters.
- Never commit real match footage (it shows minors) or model weights.

## Docs and decisions
- If a task conflicts with a decision record in `docs/decisions/`, stop and ask. If the
  decision changes, write a new record that supersedes the old one.
- Change a design doc in the same commit as the code that contradicts it.
- Start with `docs/README.md`. The JSONL schema draft is `docs/design/schema.md`.

## License
GPL-3.0-or-later (docs/decisions/0001).
