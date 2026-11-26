# CFP Research — Fixing the CFP rankings
Mission: Build (1) the Open Ranking, a reproducible wins-above-bubble ledger; (2) the Shadow Committee, which forecasts the next CFP top 25 and the final field; and (3) the Committee Gap. docs/PROPOSAL.md is authoritative; docs/SPEC.md numbers its requirements. If code and spec disagree, the spec wins. Raise the conflict, don't improvise.

## Boundary
src/cfp/open_ranking reads only: games, with the three hand-verified annotation lists (data/title_games.csv, data/forfeits.csv, data/unplayed_games.csv); teams; membership. Games, teams and membership come through OpenRankingView. It never reads committee releases, polls, lines, markets or remarks, and its settings are never tuned against them. Forecasts may read Open Ranking output. Team playoff-futures prices are for evaluation only and never enter a predictor.

## Invariants (tests enforce these)
- Integer centipoints. q = round_half_even(p*10^4). Win 10000-q; loss -q; FCS win 0; FCS loss -9900; title games full weight.
- An ordinary FBS flip changes the total by exactly 10000. A team's own margins never change its total.
- No input with first_public_time > issue_time. In live mode, ingest_time <= issue_time too.
- Published editions are write-once. Corrections create new editions.
- Every random draw uses a recorded seed.

## Glossary
bubble band, reference p, ledger, canonical points, isolated pair, rule_version_id, edition, vintage {live, archived_authentic, reconstructed, unknown}, issue (sun0200 | tminus60), lift.

## Commands
setup `uv sync` | test `uv run pytest -q` | lint `uv run ruff check .` | types `uv run mypy src` | boundary `uv run lint-imports` | gate `uv run cfp gate <edition>`

## Working rules
Read docs/PROTOCOL.md before any build task. Write failing tests first. Log decisions in docs/DECISIONS.md with SPEC IDs. Update docs/PROGRESS.md at the end of every session.

## Never
- Choose Open Ranking settings using committee rankings, polls or odds.
- Use a post-issue input.
- Edit lake/editions/** or frozen/**.
- Invent data. If a source is missing, fail loudly and record it in docs/DATA_GAPS.md.
- Claim a test passed without running it and pasting the output.
- Trade or advise on covered markets.

## Project notes (added to the pack's CLAUDE.md)
- docs/DECISIONS.md overrides prompt wording where they differ. In particular, title games use the official site flag, not forced neutral.
- lake/editions/** and frozen/** are written only by the `cfp` CLI, never by an edit or a shell redirect.
- Public display names: "Open Ranking" for the project and ranking, "Open Ranking Models" for the forecasts. Internal names are unchanged.
- The build prompts (P00–P27) are in docs/source/FinalBuildCFPRankingsStuff.pdf; the pilot order and cut lines are in docs/PLAN.md.
- API keys live in .env (CFBD_API_KEY, ODDS_API_KEY). Never read or print it.
