---
name: issue-sunday
description: Issue the 2 a.m. ET Sunday weekly and field forecasts.
---
Before any pairing file is committed for the issue, run `scripts/check_hook.sh` (prints core.hooksPath; stop if it is not scripts/hooks). Confirm the clock is at or after 07:00 UTC (EST) or 06:00 UTC (EDT). Run `cfp forecast issue --kind sun0200`. Hash the bundle, post the hash (git tag, RFC 3161, public post) and record the posting times.

## Saturday 19:00 ET go/no-go report (Issue 1; the same steps serve Issue 2 on Monday 18:00 ET)

A new session can produce this from the repository alone. Rulings are in docs/DECISIONS.md (26 and 27 Nov 2026).

1. `scripts/check_hook.sh`, then `uv run cfp forecast pairings --season 2026 --cutoff 2026-11-29T07:00:00+00:00`.
   Note the FILE line, the SECTION line, the scenario count per conference and their product.
2. For each conference with scenarios on file or still open (Big Ten, SEC, Sun Belt, Mountain West, American,
   MAC), look up the results of the week's games that decide it and the conference's own announcements. A
   settled row needs the conference's release, or the conference's published scenario plus a result that
   turns on game results alone (with `result_url`). A ranking or computer branch stays a scenario until the
   conference announces. Mountain West and American lists are entered only once games have pruned them.
3. Propose each new or pruned row to John with its URLs. Write rows only with `scripts/pairing_rows.py`,
   rerun the check, commit through the hook, and push only on John's OK.
4. Shares of the other conferences' place: on a scratch copy of the data repository (never the local
   `lake/`), run `cfp forecast issue ... --now <after the cutoff> --no-proof --allow-unresolved` with a
   scratch `--data` directory and read `other_conferences_place` in the edition's field section. An open
   league above 5% means the section is not delivered.
5. Work out the smallest product that could be on file by 23:45 ET: which deciding games end before then,
   and which pairings wait on a conference decision (the Mountain West's computer metrics come on Sunday
   morning unless UNLV loses to Nevada, a game that kicks off at 21:00 ET).
6. The call. If that smallest product is above eight, or a league above 5% cannot be settled or listed by
   23:45 ET: Issue 1's field section is not delivered, the reason names the leagues, and there is no late
   entry session. Otherwise the 23:00 to 23:45 ET entry session runs. The limit of eight and the 5% rule are
   never relaxed, and the trigger time does not move.
7. Send John: the shares, the scenario count per conference, the product, the smallest reachable product,
   and the call.
