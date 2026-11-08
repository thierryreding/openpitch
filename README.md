# OpenPitch

Football video tools for amateur coaches: cut clips from sideline footage, and (later)
detect and track players, map them onto a pitch model and analyze the game. Football
(soccer) first, American football second.

Status: early scaffolding, no features yet. See [docs/](docs/) for the design and
[decision records](docs/decisions/).

## Development

```sh
uv sync                      # core + cli
uv sync --extra studio       # + PySide6 Studio
uv sync --extra gpu          # + inference stack (CUDA)
uv run pytest
uv run ruff check && uv run ruff format --check
```

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
