# Progress

Updated at the end of every session (docs/PROTOCOL.md).

## 2026-11-25 — P00 Bootstrap + P-SPEC

Done
- Repo, signing, pack files (CLAUDE.md, PROTOCOL.md, 8 agents, 8 skills, settings, guard hook).
- uv project (Python 3.12), `src/cfp` skeleton, `cfp` CLI stub, CI workflow.
- Boundary: three import-linter contracts; `test_import_boundary` runs them in the suite.
- P00 acceptance: smoke tests pass; contract proven to fail on a planted `open_ranking -> forecast` import, probe deleted.
- `docs/SPEC.md` written with traceability table. No model code.

Commands run: `uv sync`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports`, `uv run pytest -q` (18 passed).

Open
- spec-guardian review of SPEC.md against the proposal PDF.
- Repo is private; must be public before Issue 1 (Sun 29 Nov 07:00 UTC).

Next prompt: P01 (store and point-in-time API), then P02a/P02b, P03, P04, P15, P23 per docs/PLAN.md §7.

## 2026-11-25 — P01 Store and point-in-time API (DS-01..DS-04)

Done
- `cfp.store.schemas`: 12 tables, each with the six provenance fields and vintage; validation on write.
- `cfp.store.lake`: raw payloads addressed by SHA-256; append-only Parquet partitioned by season; rejects rows citing a missing raw payload and duplicate (key, correction_version).
- `cfp.store.asof`: `as_of(rows, spec, t, mode)` with live / replay / scored modes and a coverage report.
- `cfp.store.views`: `OpenRankingView` (games, teams, membership only) and `PointInTimeView`.
- Guard hook: fixed false positives on the bare word for the frozen-parameters folder; hook behaviour is now covered by tests.
- SPEC.md revised after spec-guardian review (see DECISIONS.md).

Budget: as_of over 1,000,000 rows = 31 ms (budget 1 s).

Open
- SC-04a (open-points vintage for the Sunday issue) and the forfeit interpretation need John's decision.
- Scored mode drops only unknown vintage, as the spec says; reconstructed rows are kept and counted in coverage.

### P01 review round (same day)

spec-guardian confirmed six defects in the first P01 commit; all fixed with tests (see DECISIONS.md "P01 store rules"): backdatable ingest_time, non-atomic multi-season batches, unvalidated raw hashes, a bypassable OpenRankingView, weak import contracts, and silent drops in scored mode.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports` (4 kept, 0 broken), `uv run pytest -q` (129 passed). Budget: as_of over 999,999 lake-backed rows with three corrections per key = 24 ms.

Still to build for DS-04: `test_open_ranking_runs_without_forbidden_tables` (needs editions, P14).

Next prompt: P02a (CFBD client), P02b (CFP releases).

## 2026-11-25 — P02a (CFBD) and P02b (CFP releases)

Decisions: John ruled on SC-04a, forfeits and replay/ingest time, and set conditions for P02 (DECISIONS.md). SPEC.md updated; no [OPEN] items remain. One proposal awaits John: a Selection Day Open Ranking edition with cutoff Sun 6 Dec 02:00 ET.

Done
- `cfp.ingest.http`: one fetch path with token bucket, monthly budget and stage limits (written before each call), retries with jitter, raw archive, fetch log, key scrubbing.
- `cfp.ingest.public_time`, `cfp.ingest.upsert`: err-late first-public rules (kickoff + 4.5 h) and change-only appends.
- `cfp.ingest.cfp_releases` + `cfp ingest releases`: parse, sourced show time, alias resolution, cross-check, Wayback verification, vintage.
- **The four 2026 releases are in the lake** (100 rows), each identical to ESPN's copy. Vintage: release 1 archived_authentic, 2 and 3 reconstructed, 4 live.
- `cfp.ingest.cfbd`, `cfbd_normalize`, `cfp ingest cfbd`: client, parsers and staged season ingest, written against CFBD's published schema.
- Tests: no key-shaped string under tests/, and configured keys appear in no tracked file.

Blocked
- **CFBD rejects the key (HTTP 401).** Three calls were attempted; none succeeded. No games, polls or lines yet, and 2014–25 releases wait on the CFBD cross-check. See DATA_GAPS.md.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (31 files), `uv run lint-imports` (4 kept), `uv run pytest -q` (180 passed), `uv run cfp ingest releases --season 2026` (new=100).

Next: once the key works — `scripts/cfbd_fixture_calls.py`, then `cfp ingest cfbd --season 2026 --what reference games rankings --stage season-2026`, then 2014–25 rankings and games, `cfp ingest releases --season 2014..2025`, lines last. Then P03.

### P02 review round and live ingest (same day)

- spec-guardian confirmed sixteen defects in the first P02 commit; all fixed with tests (DECISIONS.md). One of them, the .env loader keeping an inline comment, was the cause of the CFBD 401s.
- CFBD live calls, in John's order: fixtures (9), 2026 season (10, including a rerun), 2014–25 games and polls (35), lines (26). 118 calls used this month against an allowance of 700.
- In the lake: 31,269 game rows (2014–2026), 9,855 poll rows, 38,479 closing-line rows, and 70 committee releases (1,750 rows) for every season except 2019. Release vintage: 30 archived_authentic, 1 live, 39 reconstructed.
- Recorded, trimmed fixtures now back the CFBD parser tests.

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src`, `uv run lint-imports` (4 kept), `uv run pytest -q` (206 passed), `cfp ingest cfbd ...` and `cfp ingest releases ...` as above.

Open
- 2019 releases (CFBD lacks one); three confirmations from John (Selection Day edition, narrower "live" label, Selection Day public time).

Next prompt: P03 (team identity and membership), then P04, P15, P23.

## 2026-11-25 — P03 (identity and membership) and P02d (Kalshi and Polymarket readers)

Decisions: John approved ESPN for 2019, confirmed the Selection Day edition (cutoff Sun 6 Dec 02:00 ET) and the show-start public time, and left the "live" label to Claude (kept narrow). 2019 releases are in: 76 releases, 2014–2026.

Done
- `cfp.identity`: builder, exact-match resolver, dated membership lookup, `cfp identity build`. In the lake: 777 teams, 2,334 aliases, 5,985 membership rows (2014–2026). Every team ID in games, polls and releases resolves; FBS counts match the sourced figures (138 in 2026).
- `cfp.markets`: read-only Kalshi and Polymarket parsers, `cfp markets snapshot` and `cfp markets history`. First snapshot 25 Nov 16:51–16:55 UTC: 1,582 contracts, 1,999 quotes including 417 order books. Venue history back to 26 Oct: 58,394 Kalshi candles and 68,365 Polymarket price points.
- New tables `market_catalogue`; `market_quotes` keyed with `kind`. Fifth import contract: forecasts cannot import market code.
- spec-guardian review: twelve findings fixed (DECISIONS.md).

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (36 files), `uv run lint-imports` (5 kept), `uv run pytest -q` (243 passed), `cfp identity build`, `cfp markets snapshot`, `cfp markets history --hours 720`.

Open
- Snapshots run only by hand; a schedule around each issue time is still to set up.
- John: are North Dakota State and Sacramento State ordinary FBS opponents in 2026? John: Odds API plan and tier, for P02c.
- P04 carry-overs: title-game list for 2014–21, forfeit list, left-out games, `data/transitioning.csv`.

Next prompt: P04 (canonical games), P02c once John's plan is known, then P15, P23.

## 2026-11-25 — P04 (snapshot builder), P02c (The Odds API), FBS classification ruling

Decisions: John ruled that a reclassifying member in an FBS conference is FBS for the ledger, with bid eligibility as a separate sourced flag; approved P04; set the Odds API tier (15M shared, be realistic) and accepted a 50,000-credit project cap.

Done
- Identity build enforces the classification rule and writes 29 sourced eligibility rows; membership rows carry a source URL.
- `cfp.snapshot`: `build_snapshot` and `cfp snapshot build`. Snapshots build for every season 2014–2026 with the right number of title games (7 to 10 a season). 2026 at the Issue 1 cutoff today: 824 games, 697 FBS v FBS.
- Sourced lists installed: 120 title games, no forfeits, 105 unplayed 2020 dates.
- `cfp.ingest.odds_api` and `cfp ingest odds`: 6 credits used; lines from US books for all 69 listed games.
- Hourly capture script (markets, then odds) in John's crontab, plus runs just before each pilot cutoff.
- spec-guardian review: findings fixed (DECISIONS.md).

Commands run: `uv run ruff format .`, `uv run ruff check .`, `uv run mypy src` (39 files), `uv run lint-imports` (5 kept), `uv run pytest -q` (272 passed), `cfp identity build`, `cfp snapshot build` for 2014–2026, `cfp ingest odds` (twice).

Open
- Cloud captures run hourly from the private `jpt129/open-ranking-data` repository (first run 17:46 UTC 25 Nov, 1,908 quotes). Odds lines there wait for John to add the `ODDS_API_KEY` secret.
- Fill in the 2026 title pairings after 28 Nov.
- P07 carry-over: `test_loss_to_first_year_fbs_member_scores_minus_q`. P16: CFBD ingest immediately before each cutoff.
- Odds API historical snapshots wait for John's plan.

Next prompt: P15 (bracket rules) and P23 (baselines), then P05–P08.

## 2026-11-25 — P15 (observations and baselines), P23 (issue pipeline and proof), cloud captures

Done
- Cloud capture: private `jpt129/open-ranking-data` runs markets and odds hourly on GitHub Actions (both verified).
- `cfp.forecast`: cutoffs, observations, tiebreak draw, Baseline 1 and 2, and `build_issue`.
- `cfp.release`: canonical edition bytes, input IDs, write-once edition folders, RFC 3161 request and check, signed-tag commands, post text.
- Commands: `cfp ingest ap-others`, `cfp forecast draw`, `cfp forecast issue`.
- Data: 2026 AP votes outside the top 25 (weeks 2–13); `data/preseason_draw_2026.csv`.
- Dry run on real data in a scratch copy (nothing written to `lake/editions`): last week's release forecast, Baseline 2 22/25.
- Both timestamp authorities granted a token for the dry-run hash; local tag signing works.

Tests: 295 passed. ruff, mypy (47 files), lint-imports (5 kept) clean.

Open
- Sunday's issue needs, before 02:00 ET: a CFBD games ingest after the last final, `cfp ingest ap-others` is not needed again until the next AP poll (Sunday afternoon, before Issue 2).
- The signed tag proves nothing publicly until the repository is public and the tag is pushed (`--push`).
- Issue runs still depend on John's Mac; an Actions job for issues is not built.
- Rank-noise temperature; open points (after P05–P08).

Next prompt: P11-lite, then P05–P08 (the ledger).

## 2026-11-25 (later) — review fixes; issues on GitHub Actions

Done: P15/P23 review findings fixed (304 tests); `scripts/issue.sh`; `issue` workflow in the data repository, rehearsed once.

John has since added the CFBD and issuer secrets and made the code repository public; rehearsal 2 on Actions passed every step.

## 2026-11-25 (evening) — Open Ranking core: P05, P06, P11-lite, P07, P08

Built: strength engine, reference band, link, calibration search and report, frozen-parameter files, ledger, ordering. 351 tests pass; ruff, mypy and the five import contracts are clean.

Calibration on 2015–2025 chooses λ_c = 4, λ_u = 4, t = 5.75. Nothing is frozen yet.

Waiting on John:
- Go-ahead to run `cfp calibrate freeze --season 2026` (write-once).
- Ruling on scoring calibration from week 8 only.
- Ruling on the "losses since" rule in Baseline 2 (still Claude's reading).
- Delete `~/issuer_key` (the private key) from this machine if it is still there.
- 2026 title-game pairings in `data/title_games.csv` after 28 Nov, before Issue 3.

Next: review fixes from spec-guardian and numerics-reviewer; Open Ranking release step (edition, manifest hashes); wire open points into the forecast (SC-04a).

Not confirmed: that the hourly cloud capture fires on schedule (only hand-triggered runs were observed).
