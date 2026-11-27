---
name: release-open-ranking
description: Build, gate and publish an Open Ranking edition.
---
Args: season, cutoff_utc. Run, in this order:

0. `scripts/check_hook.sh` (prints core.hooksPath; stop if it is not scripts/hooks), then
   `uv run cfp forecast pairings --season <season>`: FILE must read VALID, because the build reads
   data/title_games.csv
1. `uv run cfp open-ranking build`
2. `uv run cfp open-ranking sensitivity --edition <id>` (VT-08; about half a minute on eight cores; it stops
   itself after ten minutes and writes nothing)
3. `uv run cfp gate <id>`
4. `uv run cfp publish --edition <id>`

Never pass --force. If the gate fails, log it to DATA_GAPS.md and stop.

Sensitivity never holds the edition back. If step 2 fails or is slow, go on to steps 3 and 4: the page then
lists sensitivity as not delivered. Run step 2 before step 4, because a published page is not rewritten. The
gate reruns ten of the refits; if that rerun fails, the edition still passes and the page leaves the
sensitivity section out.
