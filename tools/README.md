# Tools

Scripts for measuring and inspecting footage. They are not part of the package. Run them
from the repository root with `uv run python tools/<path>`, and never commit footage or
output that contains it.

| script | purpose |
|---|---|
| `dji_metadata.py dump\|fields\|diff VIDEO...` | decode the per-frame protobuf metadata tracks of DJI recordings (`CAM meta`, `CAM dbgi`) without a schema; `diff` compares two recordings, e.g. two FOV settings |
| [`benchmarks/`](benchmarks/README.md) | raw measurement scripts behind the numbers in `docs/design/video.md` |
