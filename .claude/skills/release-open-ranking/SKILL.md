---
name: release-open-ranking
description: Build, gate and publish an Open Ranking edition.
---
Args: season, cutoff_utc. Run `uv run cfp open-ranking build`, then `cfp gate`, then `cfp publish`. Never pass --force. If the gate fails, log it to DATA_GAPS.md and stop.
