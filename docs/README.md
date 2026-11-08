# OpenPitch documentation

- [decisions/](decisions/): decision records for hard-to-reverse choices. These are never
  rewritten. A change is a new record that supersedes the old one.
- [design/](design/): living design docs, edited in place as the design evolves.
  - [overview.md](design/overview.md): goals, users, scope, roadmap
  - [architecture.md](design/architecture.md): packages, job API, backends, distribution
  - [video.md](design/video.md): decoding, keyframes, seeking, proxies, footage facts
  - [pipeline.md](design/pipeline.md): extraction stages, calibration, homography, teams
  - [workflows.md](design/workflows.md): ingest pass and coach pass
  - [schema.md](design/schema.md): JSONL schema draft (replaced by generated docs later)
  - [models.md](design/models.md): models and references to evaluate
- Open questions and tasks are GitHub issues, labeled `question`, `decision-needed`,
  `task`, etc. [issues/](issues/) holds drafts until they are filed.

Update a doc in the same commit as the code that changes what it describes.

[PLANNING.md](PLANNING.md) is the original planning log, kept for reference. It has been
split into the documents above, which take precedence where they differ.
