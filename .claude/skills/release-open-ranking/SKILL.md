---
name: release-open-ranking
description: Build, gate and publish an Open Ranking edition.
---
Args: season, cutoff_utc. One machine, one commit of the code. Run, in this order, and write each result
in `docs/RELEASE_LOG.md` as you go:

0. Code: `git status` must be clean; log `git rev-parse HEAD`. `scripts/check_hook.sh` (prints
   core.hooksPath; stop if it is not scripts/hooks). Then the golden test, on this machine and this commit:
   `uv run pytest -q tests/unit/test_golden_edition.py`. Stop if it fails.
1. Store: a fresh copy of the data repository, never the local `lake/`:
   `gh repo clone jpt129/open-ranking-data <dir>` (a new, empty directory).
   Every later command takes `--lake <dir>/lake`.
2. Results: `uv run cfp --lake <dir>/lake ingest cfbd --season <season> --what games --stage or-<MMDD>`.
   Then, in `<dir>`: `git add lake`, commit, `git pull --rebase`, `git push`. Log the commit hash of
   `<dir>` after the push: that is the store the edition is built from.
3. `uv run cfp forecast pairings --season <season>`: FILE must read VALID, because the build reads
   data/title_games.csv
4. `uv run cfp --lake <dir>/lake open-ranking build --season <season> --cutoff <cutoff_utc>`. Log the
   edition id, its SHA-256 and the snapshot hash from the edition's manifest.
5. `uv run cfp --lake <dir>/lake open-ranking sensitivity --edition <id>` (VT-08; about half a minute on
   the Mac; it stops itself after ten minutes and writes nothing)
6. `uv run cfp --lake <dir>/lake gate <id>`
7. `uv run cfp --lake <dir>/lake publish --edition <id>`
8. In `<dir>`: commit and push the edition, as in step 2. Log that commit hash too.

A rehearsal stops after step 6, uses a cutoff of its own, and pushes nothing in step 2 or 8.

Never pass --force. If the gate fails, log it to DATA_GAPS.md and stop.

Sensitivity never holds the edition back. If step 5 fails or is slow, go on to steps 6 and 7: the page then
lists sensitivity as not delivered. Run step 5 before step 7, because a published page is not rewritten. The
gate reruns ten of the refits; if that rerun fails, the edition still passes and the page leaves the
sensitivity section out.
