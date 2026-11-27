# Pilot runbook, 2026 (P24)

All four issues run from `jpt129/open-ranking-data`'s `issue` workflow, which checks out code and data once
at its start, runs `scripts/issue.sh` (ingest, market capture, `cfp forecast issue`), waits for the cutoff
itself and refuses to write an edition twice. Rulings and their reasons are in `docs/DECISIONS.md`.

## Times

| Issue | Kind | Cutoff (UTC) | Cutoff (ET) | First trigger (ET) | Mac fallback (ET) | Reveal (ET) |
|---|---|---|---|---|---|---|
| 1 | sun0200 | Sun 29 Nov 07:00 | 02:00 | 00:00 | 00:10, 01:10, 01:40 | Tue 1 Dec 19:00 |
| 2 | tminus60 | Tue 1 Dec 23:00 | 18:00 | 16:00 | 16:10, 17:10, 17:40 | Tue 1 Dec 19:00 |
| 3 | sun0200 | Sun 6 Dec 07:00 | 02:00 | 00:00 | 00:10, 01:10, 01:40 | Sun 6 Dec 12:00 |
| 4 | tminus60 | Sun 6 Dec 16:00 | 11:00 | 09:00 | 09:10, 10:10, 10:40 | Sun 6 Dec 12:00 |

Open Ranking editions: Monday 30 Nov, cutoff 06:00 ET; Selection Day, cutoff Sun 6 Dec 02:00 ET.

## Before each issue

1. `scripts/check_hook.sh` prints `core.hooksPath`; stop if it is not `scripts/hooks`.
2. Pairing files on main by the cut-off: 23:45 ET Saturday for Issues 1 and 3 (proposed for 3), 15:45 ET
   Tuesday for Issue 2 (target 18:00 ET Monday). Rows are written with `scripts/pairing_rows.py`.
3. `uv run cfp forecast pairings --season 2026 --cutoff <cutoff>`: FILE must read VALID before a push.
   The SECTION line says whether the field section would be delivered.
4. The Mac is awake, online and on power for the fallback (`scripts/mac_fallback/README.md`).
5. `uv run cfp budget`: keep 300 CFBD calls in reserve through 30 Nov.
6. Saturday 28 Nov, 19:00 ET: go/no-go report (shares, counts, product, smallest product reachable by 23:45).

## Minimum inputs and fallbacks

| Missing | What happens | Shown as |
|---|---|---|
| The fitted model's inputs | Baseline 2 is the labelled forecast | stated in the edition |
| A named conference's pairing, more than eight combinations, or an open league above 5% | Top 25 goes out; no field section | "not delivered", reason stated |
| An unreadable title file | Top 25 goes out; no open points, no field section | reason stated (fix deferred to after the pilot) |
| Game lines | Game probabilities from the strength model | disclosed |
| GitHub's scheduler | The Mac's launchd jobs start the workflow | trigger log |
| An issue not written before the reveal | The forecast is missing; `cfp forecast issue` refuses to run after the reveal | marked missing; never back-filled |
| Market quotes within the filters | The row is unmatched | counted in the contest report |

Nothing is filled with a substitute. Every gap goes in `docs/DATA_GAPS.md`.

## Hash posting

`cfp forecast issue` writes the edition, computes its SHA-256, creates the signed tag, requests the RFC 3161
token and prints the post text. Record the posting times. Where and when the hash becomes public relative
to the cutoff is measured in Friday's dry run and recorded here afterwards.

## After each reveal

1. `uv run cfp ingest releases --season 2026`, then check the release against the CFP page (`/ingest-release`).
2. `uv run cfp score --release <id>`: every edition issued for the reveal; conditional editions in their
   own rows; misses listed.
3. `uv run cfp gap --release <id>`: flags are provisional before Selection Day.
4. Market contest: not built. If the preregistration was not hashed before Issue 1, report "market contest
   not run"; price history that cannot be verified is marked so.

## Open Ranking edition (Monday and Selection Day)

One commit, one machine: `/release-open-ranking` (hook check and pairings check, build, sensitivity, gate,
publish). John pushes `site/`. Rerun the pairings check on Sunday afternoon: the build reads
`data/title_games.csv`.

## After 6 Dec

Remove the Mac launchd jobs (`scripts/mac_fallback/README.md`).
