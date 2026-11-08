@AGENTS.md

## Claude Code
- Scoped rules live in `.claude/rules/` and load when you touch matching files. Every rule
  file has `paths:` frontmatter. A rule file without it would load into every session.
- Before ending a session, ask whether any decision changed, and update or supersede the
  records in `docs/decisions/` accordingly.
