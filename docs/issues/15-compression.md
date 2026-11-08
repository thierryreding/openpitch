---
title: Schema: plain .jsonl vs .jsonl.zst for long matches
labels: question,schema
---

4K matches produce many detections per frame. Measure file sizes, then decide whether to support zstd-compressed JSONL. Keep in mind that Studio needs to tail append-only files.
